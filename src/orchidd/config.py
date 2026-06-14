import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OrchiddSettings:
    socket_path: Path = Path("/var/run/orchidd.sock")
    acl_path: Path = Path("~/.orchid/orchidd_acl.json").expanduser()
    log_dir: Path = Path("/var/log/orchidd")
    max_file_size: int = 10 * 1024 * 1024  # 10 MB
    exec_timeout: float = 30.0
    exec_output_cap: int = 1024 * 1024  # 1 MB

    @classmethod
    def from_env(cls) -> "OrchiddSettings":
        return cls(
            socket_path=Path(os.environ.get("ORCHIDD_SOCKET", "/var/run/orchidd.sock")),
            acl_path=Path(os.environ.get(
                "ORCHIDD_ACL", "~/.orchid/orchidd_acl.json"
            )).expanduser(),
        )
