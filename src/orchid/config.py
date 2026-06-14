import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    orchid_home: Path
    claude_config_dir: Path
    host: str = "127.0.0.1"
    port: int = 4242
    block_preview_cap: int = 16384
    external_window_s: float = 45.0
    # Optional Pushover push notifications (both must be set to enable).
    pushover_token: str | None = None
    pushover_user: str | None = None
    # Public base URL used to build deep links in notifications. Defaults to
    # http://<host>:<port>; set ORCHID_BASE_URL to a LAN/Tailscale URL so a push
    # tapped on a phone resolves to a reachable address.
    base_url: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            orchid_home=Path(os.environ.get("ORCHID_HOME", "~/.orchid")).expanduser(),
            claude_config_dir=Path(os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")).expanduser(),
            host=os.environ.get("ORCHID_HOST", "127.0.0.1"),
            port=int(os.environ.get("ORCHID_PORT", "4242")),
            pushover_token=os.environ.get("ORCHID_PUSHOVER_TOKEN") or None,
            pushover_user=os.environ.get("ORCHID_PUSHOVER_USER") or None,
            base_url=os.environ.get("ORCHID_BASE_URL") or None,
        )

    @property
    def public_base_url(self) -> str:
        return (self.base_url or f"http://{self.host}:{self.port}").rstrip("/")

    @property
    def registry_path(self) -> Path:
        return self.orchid_home / "registry.json"

    @property
    def web_dist(self) -> Path:
        return Path(__file__).resolve().parents[2] / "web" / "dist"
