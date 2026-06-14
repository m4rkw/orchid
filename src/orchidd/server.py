"""asyncio Unix domain socket server for orchidd."""

import asyncio
import logging
import os
import shlex
import time
from pathlib import Path
from typing import Any

from . import acl, ops, protocol
from .config import OrchiddSettings

log = logging.getLogger(__name__)


class OrchiddServer:
    def __init__(self, settings: OrchiddSettings):
        self._settings = settings
        self._server: asyncio.Server | None = None
        self._start_time = time.monotonic()

    async def start(self) -> None:
        sock_path = self._settings.socket_path
        sock_path.parent.mkdir(parents=True, exist_ok=True)
        sock_path.unlink(missing_ok=True)
        self._server = await asyncio.start_unix_server(
            self._handle_client, path=str(sock_path),
        )
        os.chmod(sock_path, 0o660)
        if os.getuid() == 0:
            import grp
            try:
                staff_gid = grp.getgrnam("staff").gr_gid
            except KeyError:
                staff_gid = 20
            os.chown(sock_path, 0, staff_gid)
        log.info("orchidd listening on %s", sock_path)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        self._settings.socket_path.unlink(missing_ok=True)

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername") or "unknown"
        log.debug("client connected: %s", peer)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    req = protocol.decode(line)
                except Exception:
                    resp = protocol.error_response("?", "INVALID", "malformed JSON")
                    writer.write(protocol.encode(resp))
                    await writer.drain()
                    continue
                resp = await self._dispatch(req)
                writer.write(protocol.encode(resp))
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    async def _dispatch(self, req: dict[str, Any]) -> dict[str, Any]:
        rid = req.get("id", "?")
        op = req.get("op", "")
        params = req.get("params", {})
        project_root = req.get("project_root", "")

        if op not in protocol.VALID_OPS:
            return protocol.error_response(rid, "UNKNOWN_OP", f"unknown operation: {op}")

        if op == "ping":
            return protocol.ok_response(rid, {
                "version": "0.1.0",
                "uptime": round(time.monotonic() - self._start_time, 1),
            })

        grants = acl.load_acl(self._settings.acl_path)

        if project_root:
            grant = acl.find_grant(grants, project_root)
        else:
            grant = None

        if op == "check_access":
            if not project_root:
                return protocol.error_response(rid, "MISSING_ROOT", "project_root required for check_access")
            if grant is None:
                return protocol.ok_response(rid, {"granted": False, "operations": {}})
            return protocol.ok_response(rid, {
                "granted": True,
                "operations": grant.get("operations", {}),
            })

        if grant is None and not project_root:
            # Auto-resolve: find the grant from the target path or command
            if op == "exec":
                command = params.get("command", "")
                cmd = shlex.split(command) if isinstance(command, str) else list(command)
                grant = acl.find_grant_for_exec(grants, cmd)
            else:
                path = params.get("path", "")
                if path:
                    grant = acl.find_grant_for_path(grants, path)

        if grant is None:
            msg = f"no grant for project root: {project_root}" if project_root else "no matching ACL grant"
            return protocol.error_response(rid, "ACL_DENIED", msg)

        try:
            if op == "exec":
                return await self._handle_exec(rid, grant, params)
            return await self._handle_file_op(rid, op, grant, params)
        except ops.OpError as e:
            return protocol.error_response(rid, e.code, e.message)
        except Exception:
            log.exception("unexpected error in op=%s", op)
            return protocol.error_response(rid, "INTERNAL", "unexpected server error")

    async def _handle_file_op(
        self, rid: str, op: str, grant: dict, params: dict
    ) -> dict[str, Any]:
        path = params.get("path", "")
        if not path:
            return protocol.error_response(rid, "MISSING_PARAM", "path is required")
        err = acl.check_file_op(grant, op, path)
        if err:
            return protocol.error_response(rid, "ACL_DENIED", err)

        s = self._settings
        if op == "read_file":
            result = await ops.read_file(path, s.max_file_size)
        elif op == "write_file":
            content = params.get("content", "")
            mode = params.get("mode")
            result = await ops.write_file(path, content, mode, s.max_file_size)
        elif op == "edit_file":
            result = await ops.edit_file(
                path, params.get("old_text", ""), params.get("new_text", ""),
                s.max_file_size,
            )
        elif op == "delete_file":
            result = await ops.delete_file(path)
        elif op == "mkdir":
            result = await ops.mkdir(path)
        elif op == "stat":
            result = await ops.file_stat(path)
        else:
            return protocol.error_response(rid, "UNKNOWN_OP", f"unhandled: {op}")

        log.info("op=%s path=%s ok", op, path)
        return protocol.ok_response(rid, result)

    async def _handle_exec(
        self, rid: str, grant: dict, params: dict
    ) -> dict[str, Any]:
        raw_command = params.get("command", "")
        if not raw_command:
            return protocol.error_response(rid, "MISSING_PARAM", "command is required")
        if isinstance(raw_command, str):
            command = shlex.split(raw_command)
        else:
            command = list(raw_command)
        err = acl.check_exec(grant, command)
        if err:
            return protocol.error_response(rid, "ACL_DENIED", err)

        cwd = str(Path(grant["project_root"]).expanduser().resolve())
        result = await ops.run_exec(
            command, cwd, self._settings.exec_timeout, self._settings.exec_output_cap,
        )
        log.info("exec=%s exit=%s", shlex.join(command), result["exit_code"])
        return protocol.ok_response(rid, result)
