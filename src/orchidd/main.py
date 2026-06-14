"""orchidd — privilege broker daemon for Orchid.

Runs as root, listens on a Unix socket, and executes file/exec
operations gated by a per-project ACL.
"""

import asyncio
import logging
import signal
import sys

from .config import OrchiddSettings
from .server import OrchiddServer

log = logging.getLogger("orchidd")


async def _run(settings: OrchiddSettings) -> None:
    server = OrchiddServer(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    await server.start()
    log.info("orchidd started (pid=%d, socket=%s)", __import__("os").getpid(), settings.socket_path)
    await stop.wait()
    log.info("shutting down")
    await server.stop()


def run() -> None:
    settings = OrchiddSettings.from_env()
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    print(f"orchidd → {settings.socket_path}")
    asyncio.run(_run(settings))


if __name__ == "__main__":
    run()
