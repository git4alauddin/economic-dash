"""Application entrypoint; indicator routes are added in later modules."""

from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import (DatabaseSettings, SchedulerSettings, Settings,
                        get_database_settings, get_scheduler_settings, get_settings)
from app.database import Database
from app.repository import SQLiteCollectionRepository
from app.queries import DashboardQueries
from app.collectors.runner import CollectionRunner, configure_logging
from app.collectors.scheduler import CollectorScheduler


def create_app(settings: Settings | None = None, *, scheduler_settings: SchedulerSettings | None = None,
               runner: CollectionRunner | None = None,
               database_settings: DatabaseSettings | None = None) -> FastAPI:
    settings = settings if settings is not None else get_settings()
    scheduler_settings = scheduler_settings if scheduler_settings is not None else get_scheduler_settings(settings.app_env)
    database_settings = database_settings if database_settings is not None else get_database_settings(settings.app_env)
    if settings.app_env == "production" and database_settings.app_env != "production":
        raise ValueError("Production application requires production database settings.")

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database = Database(database_settings)
        await asyncio.to_thread(database.bootstrap)
        application.state.database = database
        if scheduler_settings.enabled:
            configure_logging()
        repository = SQLiteCollectionRepository(database)
        application.state.collection_repository = repository
        application.state.dashboard_queries = DashboardQueries(database)
        collection_runner = runner if runner is not None else CollectionRunner(scheduler_settings, repository=repository)
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
