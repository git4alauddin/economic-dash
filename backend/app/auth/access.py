"""One JWT/account guard for identity, dashboard reads and conditional polling."""

from app.sqlite_runtime import sqlite3
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api_errors import ApiError
from .tokens import AuthService, InvalidAccessToken
from .users import Identity

bearer = HTTPBearer(auto_error=False, scheme_name="DashboardBearer",
                    description="Short-lived JWT from /api/v1/auth/login; verified against the active account/version.")


def unavailable():
    return ApiError(503, "authentication_unavailable", "Authentication is temporarily unavailable.", headers={"Retry-After": "1"})


def authentication(request: Request) -> AuthService:
    service = getattr(request.app.state, "auth_service", None)
    if service is None:
        raise ApiError(503, "authentication_not_configured", "Authentication is not configured yet.")
    return service


def require_identity(request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> Identity:
    if credentials is None or len(request.headers.getlist("Authorization")) != 1:
        raise ApiError(401, "authentication_required", "Sign in is required.", headers={"WWW-Authenticate": "Bearer"})
    scheme, separator, supplied = request.headers["Authorization"].partition(" ")
    if scheme.lower() != "bearer" or not separator or supplied != credentials.credentials:
        raise ApiError(401, "authentication_invalid", "Sign in is required.", headers={"WWW-Authenticate": "Bearer"})
    service = authentication(request)
    try:
        return service.verify(credentials.credentials)
    except InvalidAccessToken:
        raise ApiError(401, "authentication_invalid", "Sign in is required.", headers={"WWW-Authenticate": "Bearer"}) from None
    except (sqlite3.Error, OSError):
        raise unavailable() from None
