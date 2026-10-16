"""FastAPI bootstrap, protected v1 read routes and collector lifespan."""

from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import (DatabaseSettings, SchedulerSettings, Settings,
                        get_database_settings, get_scheduler_settings, get_settings)
from app.database import Database
from app.repository import SQLiteCollectionRepository
from app.queries import DashboardQueries
from app.api import install_api
from app.auth.routes import router as auth_router
from app.auth.settings import AuthSettings
from app.auth.tokens import AuthService
from app.auth.users import UserStore
from app.collectors.runner import CollectionRunner, configure_logging
from app.collectors.scheduler import CollectorScheduler


def create_app(settings: Settings | None = None, *, scheduler_settings: SchedulerSettings | None = None,
               runner: CollectionRunner | None = None,
               database_settings: DatabaseSettings | None = None,
               auth_settings: AuthSettings | None = None) -> FastAPI:
    settings = settings if settings is not None else get_settings()
    scheduler_settings = scheduler_settings if scheduler_settings is not None else get_scheduler_settings(settings.app_env)
    database_settings = database_settings if database_settings is not None else get_database_settings(settings.app_env)
    if settings.app_env == "production" and database_settings.app_env != "production":
        raise ValueError("Production application requires production database settings.")
    auth_settings = auth_settings if auth_settings is not None else AuthSettings(app_env=settings.app_env)
    if settings.app_env == "production" and auth_settings.app_env != "production":
        raise ValueError("Production application requires production authentication settings.")

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database = Database(database_settings)
        await asyncio.to_thread(database.bootstrap)
        application.state.database = database
        application.state.auth_service = AuthService(auth_settings, UserStore(database)) if auth_settings.jwt_signing_key is not None else None
        if scheduler_settings.enabled:
            configure_logging()
        repository = SQLiteCollectionRepository(database)
        application.state.collection_repository = repository
        application.state.dashboard_queries = DashboardQueries(database)
        collection_runner = runner if runner is not None else CollectionRunner(scheduler_settings, repository=repository)
        application.state.dashboard_queries.runtime_failure_states = collection_runner.volatile_failure_states
        scheduler = CollectorScheduler(collection_runner, scheduler_settings)
        application.state.collection_runner = collection_runner
        application.state.collector_scheduler = scheduler
        scheduler.start()
        try:
            yield
        finally:
            await scheduler.stop()

    application = FastAPI(title="Economic Indicators API", version="0.1.0", lifespan=lifespan)
    install_api(application)
    application.include_router(auth_router)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "If-None-Match", "Content-Type"],
        expose_headers=["ETag", "X-Poll-Interval"],
    )

    @application.get("/")
    def index() -> dict[str, str]:
        """Return a bootstrap response, separate from the future health contract."""
        return {"message": "Economic Indicators API"}

    return application


app = create_app()
