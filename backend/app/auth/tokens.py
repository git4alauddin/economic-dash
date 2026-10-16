"""HS256 access tokens with strict claims and current private account state."""

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from uuid import uuid4

import jwt

from .settings import AuthSettings
from .users import Identity, UserStore

REQUIRED = ("sub", "iss", "aud", "exp", "iat", "nbf", "jti", "ver", "token_use")


class InvalidAccessToken(ValueError):
    pass


@dataclass(frozen=True, repr=False)
class IssuedAccess:
    token: str
    expires_at: datetime
    expires_in: int


class AuthService:
    def __init__(self, settings: AuthSettings, users: UserStore):
        if settings.jwt_signing_key is None:
            raise ValueError("Authentication is not configured.")
        self.settings, self.users = settings, users
        self._key = bytes.fromhex(settings.jwt_signing_key.get_secret_value())

    def issue(self, user: Identity) -> IssuedAccess:
        current = self.users.get(user.user_id)
        if current is None or not current.is_active or current.credential_version != user.credential_version:
            raise InvalidAccessToken("Identity is no longer active.")
        issued = int(datetime.now(timezone.utc).timestamp())
        ttl = self.settings.access_token_minutes * 60
        claims = {"sub": user.user_id, "iss": self.settings.jwt_issuer, "aud": self.settings.jwt_audience,
                  "iat": issued, "nbf": issued, "exp": issued + ttl, "jti": uuid4().hex,
                  "ver": user.credential_version, "token_use": "access"}
        token = jwt.encode(claims, self._key, algorithm="HS256", headers={"typ": "at+jwt"})
        return IssuedAccess(token, datetime.fromtimestamp(issued + ttl, timezone.utc), ttl)

    def verify(self, token: str) -> Identity:
        try:
            if not isinstance(token, str) or len(token) > 4096 or not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token):
                raise InvalidAccessToken()
            decoded = jwt.decode_complete(token, self._key, algorithms=["HS256"],
                issuer=self.settings.jwt_issuer, audience=self.settings.jwt_audience,
                leeway=self.settings.clock_skew_seconds,
                options={"require": list(REQUIRED), "strict_aud": True})
            claims, header = decoded["payload"], decoded["header"]
            if set(header) != {"alg", "typ"} or header["alg"] != "HS256" or header["typ"] != "at+jwt":
                raise InvalidAccessToken()
            if set(claims) != set(REQUIRED) or any(type(claims[k]) is not int for k in ("exp", "iat", "nbf", "ver")):
                raise InvalidAccessToken()
            if not all(isinstance(claims[k], str) and re.fullmatch(r"[0-9a-f]{32}", claims[k]) for k in ("sub", "jti")):
                raise InvalidAccessToken()
            if claims["ver"] < 1 or claims["token_use"] != "access" or claims["nbf"] != claims["iat"] or not (
                0 < claims["exp"] - claims["iat"] <= self.settings.access_token_minutes * 60
            ):
                raise InvalidAccessToken()
        except (jwt.InvalidTokenError, ValueError, TypeError, OverflowError):
            raise InvalidAccessToken("Access token is invalid.") from None
        user = self.users.get(claims["sub"])
        if user is None or not user.is_active or user.credential_version != claims["ver"]:
            raise InvalidAccessToken("Access token is invalid.")
        return user
