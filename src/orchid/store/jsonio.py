import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def load_json(path: Path, default: Any) -> Any:
    """Read JSON, tolerating absence and corruption (corrupt files are set aside)."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        bad = path.with_suffix(path.suffix + ".bad")
        try:
            os.replace(path, bad)
            log.warning("corrupt state file moved aside: %s -> %s", path, bad)
        except OSError:
            pass
        return default


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)
