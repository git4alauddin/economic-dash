"""Structured acquisition failures, without upstream response bodies."""

from dataclasses import dataclass
from enum import StrEnum


class ErrorCode(StrEnum):
    SOURCE_BLOCKED = "source_blocked"
    UNKNOWN_SOURCE = "unknown_source"
    TIMEOUT = "timeout"
    TRANSPORT = "transport_error"
    RATE_LIMITED = "rate_limited"
    UPSTREAM = "upstream_error"
    HTTP_STATUS = "rejected_http_status"
    REDIRECT = "redirect_rejected"
    CONTENT_TYPE = "invalid_content_type"
    SIZE = "payload_too_large"
    EMPTY = "empty_payload"
    NOT_MODIFIED = "unexpected_not_modified"


@dataclass
class AcquisitionError(Exception):
    source_id: str
    code: ErrorCode
    attempts: int = 0
    http_status: int | None = None
    retry_after_seconds: float | None = None

    def __str__(self) -> str:
        return f"{self.source_id}: {self.code} (attempts={self.attempts})"
