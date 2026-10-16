"""Bounded JSON sign-in and identity, using the shared application guard."""

import asyncio
import json
import sqlite3
from datetime import datetime
from typing import Annotated, Literal

from argon2.exceptions import HashingError
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.api_errors import ApiError
from app.api_models import ErrorEnvelope
from .passwords import PasswordWorkBusy
from .access import authentication, require_identity, unavailable
from .tokens import AuthService, InvalidAccessToken
from .users import Identity


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=128, repr=False)


class PublicIdentity(BaseModel):
    user_id: str
    username: str


class LoginResponse(BaseModel):
    access_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    expires_at: datetime
    user: PublicIdentity


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Repeated JSON key")
        value[key] = item
    return value


async def login_input(request: Request) -> LoginInput:
    # Use only the server's peer identity. Forwarded headers are interpreted by
    # Uvicorn only when an operator explicitly trusts the proxy (M7).
    request.app.state.login_limiter.admit(request.client.host if request.client else "unknown")
    if request.scope.get("query_string"):
        raise ApiError(422, "invalid_request", "Login accepts JSON credentials only.")
    if len(request.headers.getlist("content-type")) != 1 or request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise ApiError(415, "unsupported_media_type", "Send an application/json request.")
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise ApiError(415, "unsupported_media_type", "Compressed login requests are not supported.")
    if len(request.headers.getlist("content-length")) > 1:
        raise ApiError(400, "invalid_request", "Request length is invalid.")
    length = request.headers.get("content-length")
    if length is not None:
        if not length.isascii() or not length.isdecimal():
            raise ApiError(400, "invalid_request", "Request length is invalid.")
        if len(length) > 10 or int(length) > 4096:
            raise ApiError(413, "request_too_large", "Login request exceeds the size limit.")
    body = bytearray()
    try:
        async with asyncio.timeout(5):
            async for chunk in request.stream():
                if len(body) + len(chunk) > 4096:
                    raise ApiError(413, "request_too_large", "Login request exceeds the size limit.")
                body.extend(chunk)
    except TimeoutError:
        raise ApiError(408, "request_timeout", "Login request took too long.") from None
    try:
        data = json.loads(body.decode("utf-8"), object_pairs_hook=unique_object)
        return LoginInput.model_validate(data)
    except (ValueError, ValidationError, UnicodeError, RecursionError):
        raise ApiError(422, "invalid_request", "Supply a valid username and password JSON object.") from None


router = APIRouter(prefix="/api/v1/auth", tags=["authentication"], responses={
    status: {"model": ErrorEnvelope} for status in (400, 401, 408, 413, 415, 422, 429, 503)})


@router.post("/login", response_model=LoginResponse, summary="Exchange private account credentials for a short-lived access token",
    openapi_extra={"requestBody": {"required": True, "content": {"application/json": {"schema": LoginInput.model_json_schema()}}}})
def login(payload: Annotated[LoginInput, Depends(login_input)], service: Annotated[AuthService, Depends(authentication)]):
    try:
        user = service.users.authenticate(payload.username, payload.password)
        if user is None:
            raise ApiError(401, "invalid_credentials", "Sign-in failed.", headers={"WWW-Authenticate": "Bearer"})
        grant = service.issue(user)
    except InvalidAccessToken:
        raise ApiError(401, "invalid_credentials", "Sign-in failed.", headers={"WWW-Authenticate": "Bearer"}) from None
    except (PasswordWorkBusy, HashingError, sqlite3.Error, OSError):
        raise unavailable() from None
    return LoginResponse(access_token=grant.token, expires_in=grant.expires_in, expires_at=grant.expires_at,
                         user=PublicIdentity(user_id=user.user_id, username=user.username))


@router.get("/me", response_model=PublicIdentity, summary="Validate access token and return its current active identity")
def me(request: Request, user: Annotated[Identity, Depends(require_identity)]):
    if request.query_params:
        raise ApiError(422, "invalid_request", "Identity requests accept no query parameters.")
    return PublicIdentity(user_id=user.user_id, username=user.username)
