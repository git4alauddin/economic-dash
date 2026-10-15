"""Versioned polling choices, not promises of official release dates or freshness."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from .catalog import SourceRegistry

IST = timezone(timedelta(hours=5, minutes=30))
POLICY_VERSION = "m3-refresh-v1"


@dataclass(frozen=True)
class RefreshPolicy:
    source_id: str
    quiet: timedelta
    active: timedelta
    days: tuple[int, ...] = ()
    months: tuple[int, ...] = ()

    def is_active(self, instant: datetime) -> bool:
        local = instant.astimezone(IST)
        return (not self.months or local.month in self.months) and (not self.days or local.day in self.days)

    def next_due(self, instant: datetime) -> datetime:
        if instant.utcoffset() != timedelta(0):
            raise ValueError("Refresh scheduling requires aware UTC timestamps.")
        if not self.days and not self.months:
            return instant + self.quiet
        due = instant + (self.active if self.is_active(instant) else self.quiet)
        # Enter a release window promptly even when a quiet interval spans it.
        day = instant.astimezone(IST).date() + timedelta(days=1)
        for offset in range(370):
            boundary = datetime.combine(day + timedelta(days=offset), time(), IST)
            if boundary.astimezone(timezone.utc) >= due:
                break
            if self.is_active(boundary):
                due = boundary.astimezone(timezone.utc)
                break
        return due


POLICIES = {
    "world_bank_gdp": RefreshPolicy("world_bank_gdp", timedelta(days=7), timedelta(days=7)),
    "mospi_gdp_pib": RefreshPolicy("mospi_gdp_pib", timedelta(days=7), timedelta(days=1), months=(2, 5, 6)),
    "mospi_cpi_pib": RefreshPolicy("mospi_cpi_pib", timedelta(days=1), timedelta(hours=6), days=tuple(range(10, 17))),
    "commerce_trade_pib": RefreshPolicy("commerce_trade_pib", timedelta(days=1), timedelta(hours=6), days=tuple(range(12, 19))),
    "finance_accounts_pib": RefreshPolicy("finance_accounts_pib", timedelta(days=1), timedelta(hours=12), days=tuple(range(1, 8)) + tuple(range(25, 32))),
}


def selected_policies(registry: SourceRegistry) -> tuple[RefreshPolicy, ...]:
    if any(source not in POLICIES for source in registry.source_ids):
        raise ValueError("Every enabled source needs a reviewed refresh policy.")
    # NSE/BSE quotes have no enabled schedule until rights, sessions and cadence
    # are verified. No guessed trading calendar or weekend quote refreshes.
    return tuple(POLICIES[source] for source in registry.source_ids)
