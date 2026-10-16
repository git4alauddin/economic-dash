"""Shared safe API error; independent of routers to avoid import cycles."""


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, *, headers=None):
        self.status, self.code, self.message, self.headers = status, code, message, headers
