"""JWT-protected v1 reads; authorization precedes SQL and conditional responses."""

from datetime import datetime, timezone
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Path, Query, Request, Response
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.exceptions import HTTPException

from app import api_projection as project
from app.api_errors import ApiError
from app.auth.access import require_identity as require_dashboard_access
from app.api_models import CatalogIndicator, DashboardData, Envelope, ErrorEnvelope, HealthResponse, HistoryData, ResponsePanel, ResponseTicker
from app.queries import DashboardQueries, QueryIntegrityError, QueryLimitExceeded, UnknownIndicator, UnknownSeries
from app.migrations import SCHEMA_VERSION
from app.update_delivery import conditional_response


def queries(request: Request) -> DashboardQueries:
    service = getattr(request.app.state, "dashboard_queries", None)
    if service is None:
        raise ApiError(503, "service_unavailable", "Dashboard storage is unavailable.")
    return service


def bounded_query(request: Request) -> None:
    """Bound aggregate input and reject ambiguous repeated scalar parameters."""
    if len(request.scope.get("query_string", b"")) > 4096 or len(request.query_params.multi_items()) > 16:
        raise ApiError(422, "query_limit_exceeded", "Query parameters exceed the request limit.")
    if any(len(request.query_params.getlist(key)) > 1 for key in request.query_params if key != "period"):
        raise ApiError(422, "invalid_query", "Scalar query parameters cannot be repeated.")


class WindowQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    window: int = Field(default=5, ge=1, le=24, description="Completed periods in each series' own fiscal/calendar cadence.")


class PanelQuery(WindowQuery):
    period: list[Annotated[str, Field(max_length=100)]] = Field(default_factory=list, max_length=13, description="Repeat series_id:period_id, e.g. exports:2026-09 or gdp_growth_india:FY2025-26.")


class HistoryQuery(WindowQuery):
    series_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$", description="A series belonging to this indicator.")
    end_period_id: str | None = Field(default=None, max_length=32, description="Canonical CY/FY/month/YTD period. Omit for latest completed source period.")


def read(operation):
    try:
        return operation()
    except (UnknownIndicator, UnknownSeries):
        raise ApiError(404, "unknown_indicator_or_series", "The requested indicator or series does not exist.") from None
    except QueryLimitExceeded:
        raise ApiError(422, "query_limit_exceeded", "History has too many revisions; narrow the window.") from None
    except (QueryIntegrityError, ValidationError):
        raise ApiError(503, "stored_data_invalid", "Stored dashboard data could not be validated.") from None
    except sqlite3.Error:
        raise ApiError(503, "storage_unavailable", "Dashboard storage is unavailable.") from None
    except ValueError:
        raise ApiError(422, "invalid_query", "The period selection or query is invalid.") from None


ERRORS = {status: {"model": ErrorEnvelope, "description": description} for status, description in (
    (401, "Authentication required"), (404, "Unknown indicator or series"), (422, "Invalid query or period"),
    (503, "Storage, stored data, or authentication integration unavailable"), (500, "Invalid server response"))}
ERRORS[304] = {"description": "Representation including freshness is unchanged; no response body."}
router = APIRouter(prefix="/api/v1", tags=["dashboard"], dependencies=[Depends(require_dashboard_access), Depends(bounded_query)], responses=ERRORS)
IndicatorPath = Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")]
Service = Annotated[DashboardQueries, Depends(queries)]


@router.get("/dashboard", response_model=Envelope[DashboardData], summary="Six panels and ticker from one SQL snapshot")
def dashboard(service: Service, options: Annotated[WindowQuery, Query()], request: Request, response: Response):
    now = datetime.now(timezone.utc)
    body = read(lambda: project.dashboard(service, service.dashboard(window=options.window, now=now), now))
    return conditional_response(request, response, body)


@router.get("/indicators", response_model=Envelope[tuple[CatalogIndicator, ...]], summary="Indicator definitions and available periods within the requested window")
def indicators(service: Service, options: Annotated[WindowQuery, Query()], request: Request, response: Response):
    now = datetime.now(timezone.utc)
    body = read(lambda: project.catalog(service, service.dashboard(window=options.window, now=now), now))
    return conditional_response(request, response, body)


@router.get("/indicators/{indicator_id}", response_model=Envelope[ResponsePanel], summary="Panel summaries and histories; select each series' period independently")
def indicator(indicator_id: IndicatorPath, service: Service, options: Annotated[PanelQuery, Query()], request: Request, response: Response):
    def operation():
        selections = {}
        for item in options.period:
            sid, separator, period_id = item.partition(":")
            if not separator or not period_id or sid in selections:
                raise ValueError("Invalid/duplicate period selection")
            selections[sid] = period_id
        now = datetime.now(timezone.utc)
        value = service.indicator(indicator_id, window=options.window, end_periods=selections, now=now)
        result = project.panel(service, value, now)
        return Envelope[ResponsePanel](data=result, meta=project.meta(value.checkpoint_run_id, now,
            any(entry.latest.value is None or entry.history.status != "fresh" or any(p.value is None for p in entry.history.points) for entry in result.series.values())))
    return conditional_response(request, response, read(operation))


@router.get("/indicators/{indicator_id}/history", response_model=Envelope[HistoryData], summary="Bounded history for one series, with comparison inputs and revision trace")
def history(indicator_id: IndicatorPath, service: Service, options: Annotated[HistoryQuery, Query()], request: Request, response: Response):
    def operation():
        service._selections(indicator_id, None)
        allowed = {entry["id"] for entry in service.panels[indicator_id]["series"]}
        if options.series_id not in allowed:
            raise UnknownSeries(options.series_id)
        now = datetime.now(timezone.utc)
        return project.history(service, service.series(options.series_id, window=options.window, end_period_id=options.end_period_id, now=now), now)
    return conditional_response(request, response, read(operation))


@router.get("/ticker", response_model=Envelope[ResponseTicker], summary="Explicitly unavailable market quotes until source gates are cleared")
def ticker(service: Service, request: Request, response: Response):
    # Use the committed read snapshot for a truthful version; no quote fetching.
    def operation():
        if request.query_params:
            raise ValueError("Ticker accepts no query parameters")
        now = datetime.now(timezone.utc)
        version = service.ticker_version()
        return Envelope[ResponseTicker](data=project.ticker(service), meta=project.meta(version, now))
    return conditional_response(request, response, read(operation))


def install_api(application: FastAPI) -> None:
    application.include_router(router)

    @application.get("/health", response_model=HealthResponse, tags=["operations"],
                     responses={503: {"model": HealthResponse, "description": "Local database is not ready."}})
    def health(request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        database = getattr(request.app.state, "database", None)
        try:
            if database is None:
                raise RuntimeError("Storage is not initialized")
            with database.connection(read_only=True) as connection:
                connection.execute("PRAGMA query_only=ON")
                connection.execute("BEGIN")
                if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                    raise RuntimeError("Schema is not ready")
                connection.execute("SELECT observation_id FROM observations LIMIT 0")
                if not connection.execute("SELECT 1 FROM schema_migrations WHERE version=?", (SCHEMA_VERSION,)).fetchone():
                    raise RuntimeError("Migration is not ready")
        except (sqlite3.Error, OSError, RuntimeError):
            response.status_code = 503
            return HealthResponse(status="unavailable")
        return HealthResponse(status="ok")

    @application.middleware("http")
    async def private_api_responses(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @application.exception_handler(ApiError)
    async def api_error(request, error):
        return JSONResponse(status_code=error.status, content={"error": {"code": error.code, "message": error.message, "details": []}}, headers=error.headers)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        # No submitted values, tokens, exception context or SQL/path strings in errors.
        details = [{"location": list(item["loc"]), "message": "Invalid request parameter."} for item in error.errors()]
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_request", "message": "Request validation failed.", "details": details}})

    @application.exception_handler(HTTPException)
    async def http_error(request, error):
        return JSONResponse(status_code=error.status_code, headers=error.headers,
            content={"error": {"code": "route_not_found" if error.status_code == 404 else "request_rejected", "message": "Request could not be served.", "details": []}})

    @application.exception_handler(ResponseValidationError)
    async def response_error(request, error):
        return JSONResponse(status_code=500, content={"error": {"code": "response_invalid", "message": "Dashboard response could not be validated.", "details": []}})

    @application.exception_handler(Exception)
    async def internal_error(request, error):
        return JSONResponse(status_code=500, headers={"Cache-Control": "no-store"},
            content={"error": {"code": "internal_error", "message": "Request could not be completed.", "details": []}})
