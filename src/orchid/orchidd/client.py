"""Async client for talking to the orchidd Unix socket."""

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_SOCKET = Path("/var/run/orchidd.sock")


class OrchiddError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class OrchiddClient:
    def __init__(self, socket_path: Path = DEFAULT_SOCKET):
        self._socket_path = socket_path
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def _connect(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        if self._writer is not None:
            try:
                self._writer.write(b"")
                await self._writer.drain()
                return self._reader, self._writer  # type: ignore
            except (ConnectionError, OSError):
                await self._disconnect()
        r, w = await asyncio.open_unix_connection(str(self._socket_path))
        self._reader, self._writer = r, w
        return r, w

    async def _disconnect(self) -> None:
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = self._writer = None

    async def _request(self, op: str, project_root: str = "", **params: Any) -> dict[str, Any]:
        rid = uuid.uuid4().hex[:12]
        msg = {"id": rid, "op": op, "project_root": project_root, "params": params}
        payload = json.dumps(msg, separators=(",", ":")).encode() + b"\n"
        async with self._lock:
            try:
                reader, writer = await self._connect()
                writer.write(payload)
                await writer.drain()
                line = await asyncio.wait_for(reader.readline(), timeout=60.0)
            except (ConnectionError, OSError, asyncio.TimeoutError) as e:
                await self._disconnect()
                raise OrchiddError("CONNECTION", f"orchidd unreachable: {e}") from e
        resp = json.loads(line)
        if not resp.get("ok"):
            err = resp.get("error", {})
            raise OrchiddError(err.get("code", "UNKNOWN"), err.get("message", "unknown error"))
        return resp.get("result", {})

    async def ping(self) -> dict[str, Any]:
        return await self._request("ping")

    async def is_available(self) -> bool:
        try:
            await self.ping()
            return True
        except (OrchiddError, OSError):
            return False

    async def check_access(self, project_root: str) -> dict[str, Any]:
        return await self._request("check_access", project_root)

    async def read_file(self, project_root: str, path: str) -> dict[str, Any]:
        return await self._request("read_file", project_root, path=path)

    async def write_file(
        self, project_root: str, path: str, content: str, mode: str | None = None,
    ) -> dict[str, Any]:
        kw: dict[str, Any] = {"path": path, "content": content}
        if mode:
            kw["mode"] = mode
        return await self._request("write_file", project_root, **kw)

    async def edit_file(
        self, project_root: str, path: str, old_text: str, new_text: str,
    ) -> dict[str, Any]:
        return await self._request(
            "edit_file", project_root, path=path, old_text=old_text, new_text=new_text,
        )

    async def delete_file(self, project_root: str, path: str) -> dict[str, Any]:
        return await self._request("delete_file", project_root, path=path)

    async def mkdir(self, project_root: str, path: str) -> dict[str, Any]:
        return await self._request("mkdir", project_root, path=path)

    async def chmod(self, project_root: str, path: str, mode: str) -> dict[str, Any]:
        return await self._request("chmod", project_root, path=path, mode=mode)

    async def stat(self, project_root: str, path: str) -> dict[str, Any]:
        return await self._request("stat", project_root, path=path)

    async def exec(self, project_root: str, command: str) -> dict[str, Any]:
        return await self._request("exec", project_root, command=command)

    async def aclose(self) -> None:
        await self._disconnect()
