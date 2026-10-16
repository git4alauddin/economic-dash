"""Bounded sliding-window login admission for the single API process/worker.

All admitted POST attempts count, including success and malformed input. No
username lockout and no passwords/tokens in limiter state. Restart clears state;
M7 must preserve one worker and verify trusted proxy peers before enabling them.
"""

from collections import deque
from math import ceil
from threading import Lock
from time import monotonic

from app.api_errors import ApiError
from .settings import AuthSettings


class LoginLimiter:
    def __init__(self, settings: AuthSettings, *, clock=monotonic):
        self._client_limit = settings.login_client_attempts
        self._global_limit = settings.login_global_attempts
        self._window = settings.login_window_seconds
        self._max_clients = settings.login_max_clients
        self._clock = clock
        self._clients: dict[str, deque[float]] = {}
        self._global: deque[float] = deque()
        self._lock = Lock()

    def admit(self, client: str) -> None:
        with self._lock:
            now = self._clock()
            cutoff = now - self._window
            while self._global and self._global[0] <= cutoff:
                self._global.popleft()
            for key, attempts in list(self._clients.items()):
                while attempts and attempts[0] <= cutoff:
                    attempts.popleft()
                if not attempts:
                    del self._clients[key]
            attempts = self._clients.get(client)
            deadlines = []
            if len(self._global) >= self._global_limit:
                deadlines.append(self._global[0] + self._window)
            if attempts is not None and len(attempts) >= self._client_limit:
                deadlines.append(attempts[0] + self._window)
            if attempts is None and len(self._clients) >= self._max_clients:
                # Do not evict active clients: rotating addresses cannot reset
                # an existing budget. Refuse new entries until one expires.
                deadlines.append(min(items[-1] for items in self._clients.values()) + self._window)
            if deadlines:
                raise ApiError(429, "login_rate_limited", "Too many sign-in attempts. Please wait before trying again.",
                               headers={"Retry-After": str(max(1, ceil(max(deadlines) - now)))})
            if attempts is None:
                attempts = self._clients[client] = deque()
            attempts.append(now)
            self._global.append(now)
