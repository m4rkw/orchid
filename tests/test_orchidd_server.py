"""Integration tests for orchidd server + client over a temp Unix socket."""

import asyncio
import json
import pytest
from pathlib import Path

from orchidd.acl import save_acl
from orchidd.config import OrchiddSettings
from orchidd.server import OrchiddServer
from orchid.orchidd.client import OrchiddClient, OrchiddError

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def setup(tmp_path):
    import tempfile
    sock = Path(tempfile.mktemp(prefix="orchidd_", suffix=".sock", dir="/tmp"))
    acl_path = tmp_path / "acl.json"
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "hello.txt").write_text("world")
    (project_root / "subdir").mkdir()

    settings = OrchiddSettings(
        socket_path=sock, acl_path=acl_path,
        log_dir=tmp_path / "log", max_file_size=1024 * 1024,
        exec_timeout=10.0, exec_output_cap=65536,
    )

    save_acl(acl_path, [{
        "id": "grant_test",
        "project_root": str(project_root),
        "project_id": "prj_test",
        "permanent": True,
        "operations": {
            "file_read": True,
            "file_write": True,
            "file_delete": True,
            "exec": ["echo hello", "ls *"],
        },
    }])

    server = OrchiddServer(settings)
    await server.start()
    client = OrchiddClient(sock)
    yield client, project_root, acl_path
    await client.aclose()
    await server.stop()


async def test_ping(setup):
    client, _, _ = setup
    result = await client.ping()
    assert "version" in result
    assert result["uptime"] >= 0


async def test_read_file(setup):
    client, root, _ = setup
    result = await client.read_file(str(root), str(root / "hello.txt"))
    assert result["content"] == "world"


async def test_write_file(setup):
    client, root, _ = setup
    target = str(root / "new.txt")
    result = await client.write_file(str(root), target, "hello orchidd")
    assert result["bytes_written"] == 13
    assert Path(target).read_text() == "hello orchidd"


async def test_edit_file(setup):
    client, root, _ = setup
    result = await client.edit_file(str(root), str(root / "hello.txt"), "world", "orchidd")
    assert (root / "hello.txt").read_text() == "orchidd"


async def test_edit_file_preserves_mode(setup):
    """Regression: a surgical edit must keep the file's existing permission bits
    (a 0755 daemon dropping to 0644 stops launchd/systemd spawning it)."""
    import os
    import stat as stat_mod

    client, root, _ = setup
    target = root / "daemon.py"
    target.write_text("print('v1')\n")
    os.chmod(target, 0o755)

    result = await client.edit_file(str(root), str(target), "v1", "v2")
    assert target.read_text() == "print('v2')\n"
    assert stat_mod.S_IMODE(target.stat().st_mode) == 0o755  # not reset to 0644
    assert result["mode"] == "0755"


async def test_delete_file(setup):
    client, root, _ = setup
    target = root / "deleteme.txt"
    target.write_text("bye")
    await client.delete_file(str(root), str(target))
    assert not target.exists()


async def test_mkdir(setup):
    client, root, _ = setup
    target = str(root / "a" / "b" / "c")
    await client.mkdir(str(root), target)
    assert Path(target).is_dir()


async def test_stat(setup):
    client, root, _ = setup
    result = await client.stat(str(root), str(root / "hello.txt"))
    assert result["is_file"] is True
    assert result["size"] == 5


async def test_exec(setup):
    client, root, _ = setup
    result = await client.exec(str(root), "echo hello")
    assert result["exit_code"] == 0
    assert "hello" in result["stdout"]


async def test_exec_denied(setup):
    client, root, _ = setup
    with pytest.raises(OrchiddError) as exc:
        await client.exec(str(root), "rm -rf /")
    assert exc.value.code == "ACL_DENIED"


async def test_no_grant(setup):
    client, root, _ = setup
    with pytest.raises(OrchiddError) as exc:
        await client.read_file("/tmp/other", "/tmp/other/file.txt")
    assert exc.value.code == "ACL_DENIED"


async def test_check_access_granted(setup):
    client, root, _ = setup
    result = await client.check_access(str(root))
    assert result["granted"] is True
    assert result["operations"]["file_read"] is True


async def test_check_access_none(setup):
    client, _, _ = setup
    result = await client.check_access("/tmp/no-such-project")
    assert result["granted"] is False


async def test_path_traversal_blocked(setup):
    client, root, _ = setup
    with pytest.raises(OrchiddError) as exc:
        await client.read_file(str(root), str(root / ".." / ".." / "etc" / "passwd"))
    assert exc.value.code == "ACL_DENIED"
