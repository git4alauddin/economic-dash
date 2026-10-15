"""Application entrypoint; indicator routes are added in later modules."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import SchedulerSettings, Settings, get_scheduler_settings, get_settings
from app.collectors.runner import CollectionRunner, configure_logging
from app.collectors.scheduler import CollectorScheduler


def create_app(settings: Settings | None = None, *, scheduler_settings: SchedulerSettings | None = None,
               runner: CollectionRunner | None = None) -> FastAPI:
    settings = settings if settings is not None else get_settings()
    scheduler_settings = scheduler_settings if scheduler_settings is not None else get_scheduler_settings(settings.app_env)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if scheduler_settings.enabled:
            configure_logging()
        collection_runner = runner if runner is not None else CollectionRunner(scheduler_settings)
        scheduler = CollectorScheduler(collection_runner, scheduler_settings)
        application.state.collection_runner = collection_runner
        application.state.collector_scheduler = scheduler
        scheduler.start()
        try:
            yield
        finally:
            await scheduler.stop()

    application = FastAPI(title="Economic Indicators API", version="0.1.0", lifespan=lifespan)
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
