import uvicorn

from .config import Settings


def run() -> None:
    settings = Settings.from_env()
    print(f"⚘ Orchid → http://{settings.host}:{settings.port}")
    uvicorn.run(
        "orchid.api.app:create_app_from_env",
        factory=True,
        host=settings.host,
        port=settings.port,
        workers=1,  # in-memory bus/drivers require a single process
        log_level="info",
    )


if __name__ == "__main__":
    run()
