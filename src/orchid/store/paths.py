import shlex
from pathlib import Path


def canonicalize(path: str | Path) -> Path:
    """Resolve to an absolute, symlink-free path (macOS: /var -> /private/var)."""
    return Path(str(path)).expanduser().resolve()


def handoff_command(root: Path, session_id: str) -> str:
    return f"cd {shlex.quote(str(root))} && claude --resume {shlex.quote(session_id)}"
