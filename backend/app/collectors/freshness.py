"""Conservative application freshness policy, separate from publisher guarantees."""

import calendar
from datetime import datetime, timedelta, timezone
from typing import Literal

from .observations import ImmutableModel, NormalizedObservation
from .refresh_policy import IST, POLICIES

FRESHNESS_VERSION = "m3-freshness-v1"


class SourceState(ImmutableModel):
    source_id: str
    run_id: str | None = None
    outcome: Literal["never_observed", "updated", "unchanged", "empty", "partial", "failed"] = "never_observed"
    last_attempt_at: datetime | None = None
    last_checked_at: datetime | None = None
    last_success_at: datetime | None = None
    last_changed_at: datetime | None = None
    last_failure_at: datetime | None = None
    failure_reason: str | None = None


class SeriesFreshness(ImmutableModel):
    series_id: str
    observation: NormalizedObservation | None
    status: Literal["fresh", "stale", "unavailable"]
    reason_code: str | None
    retention_allowed: bool
    last_checked_at: datetime | None
    last_success_at: datetime | None
    retrieved_at: datetime | None
    publication_deadline: datetime | None
    check_deadline: datetime | None
    policy_version: str = FRESHNESS_VERSION


def publication_deadline(point: NormalizedObservation) -> datetime:
    """Next observation deadline plus conservative release grace, in IST.

    CPI/trade: 20th/22nd after the next observation month; fiscal accounts:
    seven days after the following month-end. Annual GDP: June 15 (India),
    September 30 (World) after the next reporting year. These are our stale
    cutoffs, not exact official release dates or an invented holiday calendar.
    """
    period, source = point.observation_period, point.sources[0].source_id
    if source == "mospi_gdp_pib":
        return datetime(period.end.year + 1, 6, 15, 23, 59, 59, tzinfo=IST).astimezone(timezone.utc)
    if source == "world_bank_gdp":
        return datetime(period.end.year + 2, 9, 30, 23, 59, 59, tzinfo=IST).astimezone(timezone.utc)
    month_number = period.end.year * 12 + period.end.month - 1 + 2
    year, zero_month = divmod(month_number, 12)
    month = zero_month + 1
    if source == "finance_accounts_pib":
        deadline = datetime(year, month, calendar.monthrange(year, month)[1], 23, 59, 59, tzinfo=IST) + timedelta(days=7)
    else:
        deadline = datetime(year, month, 20 if source == "mospi_cpi_pib" else 22, 23, 59, 59, tzinfo=IST)
    return deadline.astimezone(timezone.utc)


def freshness(series_id: str, point: NormalizedObservation | None, state: SourceState, now: datetime, *, blocked_reason: str | None = None, empty: bool = False) -> SeriesFreshness:
    if now.utcoffset() != timedelta(0):
        raise ValueError("Freshness evaluation requires aware UTC time.")
    deadline = publication_deadline(point) if point is not None else None
    check_deadline = None
    if state.last_success_at is not None:
        policy = POLICIES[state.source_id]
        grace = policy.active if policy.is_active(now) else policy.quiet
        check_deadline = policy.next_due(state.last_success_at) + max(timedelta(hours=1), grace)
    if blocked_reason:
        status, reason = "unavailable", blocked_reason
    elif point is None or point.value is None:
        status = "unavailable"
        reason = point.reason_code if point is not None else ("source_dataset_empty" if empty else "never_observed")
    elif state.failure_reason:
        status, reason = "stale", state.failure_reason
    elif state.last_success_at is None or (check_deadline is not None and now > check_deadline):
        status, reason = "stale", "refresh_check_overdue"
    elif deadline is not None and now > deadline:
        status, reason = "stale", "observation_release_overdue"
    else:
        status, reason = "fresh", None
    return SeriesFreshness(series_id=series_id, observation=point, status=status, reason_code=reason,
                           retention_allowed=not blocked_reason and point is not None and point.value is not None,
                           last_checked_at=state.last_checked_at, last_success_at=state.last_success_at,
                           retrieved_at=point.retrieved_at if point else None, publication_deadline=deadline, check_deadline=check_deadline)
