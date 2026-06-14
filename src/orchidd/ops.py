"""Privileged operations executed by orchidd.

Every function receives already-validated, canonicalized paths.
All file writes use atomic tmp+rename.
"""

import asyncio
import logging
import os
import stat as stat_mod
from pathlib import Path

log = logging.getLogger(__name__)


def _canonicalize(p: str | Path) -> Path:
    return Path(str(p)).expanduser().resolve()


async def read_file(path: str, max_size: int) -> dict:
    p = _canonicalize(path)
    if not p.is_file():
        raise OpError("NOT_FOUND", f"{p} does not exist or is not a file")
    size = p.stat().st_size
    if size > max_size:
        raise OpError("TOO_LARGE", f"{p} is {size} bytes (limit {max_size})")
    content = p.read_text(errors="replace")
    return {"content": content, "size": len(content)}


async def write_file(path: str, content: str, mode: str | None, max_size: int) -> dict:
    if len(content.encode()) > max_size:
        raise OpError("TOO_LARGE", f"content is {len(content.encode())} bytes (limit {max_size})")
    p = _canonicalize(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".orchidd_tmp")
    try:
        tmp.write_text(content)
        if mode:
            os.chmod(tmp, int(mode, 8))
        os.replace(tmp, p)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return {"bytes_written": len(content.encode()), "path": str(p)}


async def edit_file(path: str, old_text: str, new_text: str, max_size: int) -> dict:
    p = _canonicalize(path)
    if not p.is_file():
        raise OpError("NOT_FOUND", f"{p} does not exist")
    content = p.read_text(errors="replace")
    count = content.count(old_text)
    if count == 0:
        raise OpError("NOT_FOUND", "old_text not found in file")
    if count > 1:
        raise OpError("AMBIGUOUS", f"old_text appears {count} times — provide more context")
    new_content = content.replace(old_text, new_text, 1)
    if len(new_content.encode()) > max_size:
        raise OpError("TOO_LARGE", "result exceeds max file size")
    # Preserve the existing permission bits: a surgical edit must never silently
    # change a file's mode (a 0755 daemon dropping to 0644 stops launchd/systemd
    # spawning it). The tmp+rename below would otherwise inherit the tmp's 0644.
    orig_mode = stat_mod.S_IMODE(p.stat().st_mode)
    tmp = p.with_suffix(p.suffix + ".orchidd_tmp")
    try:
        tmp.write_text(new_content)
        os.chmod(tmp, orig_mode)
        os.replace(tmp, p)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return {"path": str(p), "mode": format(orig_mode, "04o")}


async def delete_file(path: str) -> dict:
    p = _canonicalize(path)
    if not p.exists():
        raise OpError("NOT_FOUND", f"{p} does not exist")
    if p.is_dir():
        raise OpError("IS_DIRECTORY", f"{p} is a directory — use rmdir or delete individual files")
    p.unlink()
    return {"path": str(p)}


async def mkdir(path: str) -> dict:
    p = _canonicalize(path)
    p.mkdir(parents=True, exist_ok=True)
    return {"path": str(p)}


async def file_stat(path: str) -> dict:
    p = _canonicalize(path)
    if not p.exists():
        raise OpError("NOT_FOUND", f"{p} does not exist")
    s = p.stat()
    import pwd
    import grp
    try:
        owner = pwd.getpwuid(s.st_uid).pw_name
    except KeyError:
        owner = str(s.st_uid)
    try:
        group = grp.getgrgid(s.st_gid).gr_name
    except KeyError:
        group = str(s.st_gid)
    return {
        "path": str(p),
        "size": s.st_size,
        "mode": stat_mod.filemode(s.st_mode),
        "owner": owner,
        "group": group,
        "mtime": s.st_mtime,
        "is_dir": p.is_dir(),
        "is_file": p.is_file(),
    }


async def run_exec(command: list[str], cwd: str, timeout: float, output_cap: int) -> dict:
    try:
        proc = await asyncio.create_subprocess_exec(
            *command, cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise OpError("TIMEOUT", f"command timed out after {timeout}s")
    except FileNotFoundError:
        raise OpError("NOT_FOUND", f"command not found: {command[0]}")
    out = stdout.decode(errors="replace")[:output_cap]
    err = stderr.decode(errors="replace")[:output_cap]
    return {"exit_code": proc.returncode, "stdout": out, "stderr": err}


class OpError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
