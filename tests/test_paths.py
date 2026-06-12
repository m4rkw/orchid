import os
from pathlib import Path

from orchid.store.paths import canonicalize, handoff_command


def test_canonicalize_resolves_symlinks(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    os.symlink(real, link)
    assert canonicalize(link) == real.resolve()
    assert canonicalize(str(link)) == real.resolve()


def test_canonicalize_expands_home():
    assert canonicalize("~/somewhere").is_absolute()
    assert str(canonicalize("~/somewhere")).startswith(str(Path.home().resolve()))


def test_handoff_command_quotes_paths():
    cmd = handoff_command(Path("/tmp/my project"), "abc-123")
    assert cmd == "cd '/tmp/my project' && claude --resume abc-123"
