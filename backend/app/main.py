"""Application entrypoint; indicator routes are added in later modules."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else get_settings()
    application = FastAPI(title="Economic Indicators API", version="0.1.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET"],
    )

    @application.get("/")
    def index() -> dict[str, str]:
        """Return a bootstrap response, separate from the future health contract."""
        return {"message": "Economic Indicators API"}

    return application


app = create_app()
