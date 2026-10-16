"""Bounded SQL reads and exact M3 calculations; HTTP/wire models belong to M4.5.

All panels in a dashboard share one read transaction. Queries never collect data,
write a checkpoint or require observations to remain in the bounded collector RAM.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
import json
import re
from typing import Mapping

from app.database import Database
from app.repository import observation_from_row
from app.collectors.catalog import CATALOG_PATH
from app.collectors.handoff import catalog_fingerprint
from app.collectors.freshness import SourceState
from app.collectors.history import (
    Comparison, HistoricalSeries, HistorySlot, UnavailableRequirement,
    _periods, _reference_period, build_history, compare,
)
from app.collectors.observations import NormalizedBatch, NormalizedObservation, ObservationPeriod, annual_period, monthly_period

MAX_QUERY_ROWS = 4096


class UnknownIndicator(ValueError):
    pass


class UnknownSeries(ValueError):
    pass


class QueryIntegrityError(ValueError):
    pass


class QueryLimitExceeded(ValueError):
    pass


@dataclass(frozen=True)
class SeriesRead:
    history: HistoricalSeries
    selected_period: ObservationPeriod | None
    latest_valid: NormalizedObservation | None
    comparison: Comparison  # Applies to latest_valid; chart gaps stay independent.
    source_states: tuple[SourceState, ...] = ()
    checkpoint_run_id: str | None = None
    history_truncated: bool = False


@dataclass(frozen=True)
class SummaryRead:
    slot: int
    requirement_id: str
    definition_id: str | None
    unit: str | None
    observation: NormalizedObservation | None
    comparison: Comparison
    reason_code: str | None


@dataclass(frozen=True)
class IndicatorRead:
    indicator_id: str
    series: tuple[SeriesRead, ...]
    summaries: tuple[SummaryRead, ...]
    source_states: tuple[SourceState, ...] = ()
    checkpoint_run_id: str | None = None


@dataclass(frozen=True)
class DashboardRead:
    checkpoint_run_id: str | None
    panels: tuple[IndicatorRead, ...]
    ticker: tuple[UnavailableRequirement, ...]
    source_states: tuple[SourceState, ...] = ()


def unavailable_comparison(reason: str) -> Comparison:
    return Comparison(value=None, unit=None, transform_id=None, current=None, reference=None,
                      reference_period_id=None, reason_code=reason)


class DashboardQueries:
    def __init__(self, database: Database):
        self.database = database
        self.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        self.inventory = json.loads((CATALOG_PATH.parent / "indicator-requirements.json").read_text(encoding="utf-8"))
        self.fingerprint = catalog_fingerprint()
        self.panels = {p["indicator_id"]: p for p in self.inventory["panels"]}
        self.series_ids = {s["id"] for p in self.panels.values() for s in p["series"]}
        # Main wires a read-only callback for explicitly uncommitted failure metadata.
        self.runtime_failure_states = lambda: ()

    @staticmethod
    def _states(connection) -> tuple[SourceState, ...]:
        return tuple(SourceState.model_validate_json(json.dumps(dict(row)))
                     for row in connection.execute("SELECT * FROM source_states ORDER BY source_id"))

    @staticmethod
    def _options(window: int, now: datetime | None) -> datetime:
        if type(window) is not int or not 1 <= window <= 24:
            raise ValueError("History window must be an integer between 1 and 24.")
        now = now if now is not None else datetime.now(timezone.utc)
        if not isinstance(now, datetime) or now.utcoffset() != timedelta(0):
            raise ValueError("Query time must be timezone-aware UTC.")
        return now

    def _begin(self, connection) -> str | None:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        if self.fingerprint != catalog_fingerprint():
            raise QueryIntegrityError("Catalog changed; create a new query service after review.")
        row = connection.execute("""SELECT r.run_id,r.catalog_fingerprint FROM repository_checkpoint p
            JOIN collector_runs r ON r.run_id=p.run_id WHERE p.singleton=1""").fetchone()
        if row is None:
            if connection.execute("SELECT 1 FROM collector_runs LIMIT 1").fetchone() or connection.execute("SELECT 1 FROM observations LIMIT 1").fetchone():
                raise QueryIntegrityError("Stored data has no committed checkpoint.")
            return None
        if row["catalog_fingerprint"] != self.fingerprint:
            raise QueryIntegrityError("Stored data belongs to a different definition catalog.")
        return row["run_id"]

    def _period(self, sid: str, period_id: str) -> ObservationPeriod:
        definition = self.catalog["requirements"][sid]
        if not isinstance(period_id, str) or len(period_id) > 32:
            raise ValueError("Invalid period identifier.")
        frequency, basis = definition["frequency"], definition["basis"]
        if frequency == "annual":
            pattern = r"CY([0-9]{4})" if basis == "calendar" else r"FY([0-9]{4})-[0-9]{2}"
            found = re.fullmatch(pattern, period_id)
            if not found:
                raise ValueError("Annual period must use the series' fiscal/calendar basis.")
            period = annual_period(int(found[1]), fiscal=basis == "fiscal")
        else:
            found = re.fullmatch(r"([0-9]{4})-([0-9]{2})", period_id) if frequency == "monthly" else re.fullmatch(r"FY[0-9]{4}-[0-9]{2}:([0-9]{4})-([0-9]{2})", period_id)
            if not found:
                raise ValueError("Monthly/YTD period must use its complete canonical identifier.")
            period = monthly_period(int(found[1]), int(found[2]), cumulative=frequency == "monthly_cumulative")
        if period.id != period_id:
            raise ValueError("Period ID does not match its fiscal/calendar bounds.")
        return period

    def _at_end(self, sid: str, value: str) -> ObservationPeriod:
        end = date.fromisoformat(value)
        definition = self.catalog["requirements"][sid]
        if definition["frequency"] == "annual":
            return annual_period(end.year - (definition["basis"] == "fiscal"), fiscal=definition["basis"] == "fiscal")
        return monthly_period(end.year, end.month, cumulative=definition["frequency"] == "monthly_cumulative")

    def _latest_end(self, connection, sid: str, cutoff: str, *, valid: bool = False) -> str | None:
        definition = self.catalog["requirements"][sid]
        row = connection.execute("""SELECT period_end FROM observations
            WHERE series_id=? AND definition_id=? AND source_id=? AND period_end<=?
            AND (?=0 OR value_decimal IS NOT NULL) ORDER BY period_end DESC LIMIT 1""",
            (sid, definition["definition_id"], definition["source_id"], cutoff, int(valid))).fetchone()
        return row[0] if row else None

    def _latest_balance_end(self, connection, cutoff: str) -> str | None:
        definitions = self.catalog["requirements"]
        row = connection.execute("""SELECT e.period_end FROM observations e JOIN observations i
            ON i.period_id=e.period_id AND i.vintage_id=e.vintage_id AND i.parser_version=e.parser_version
            AND i.source_id=e.source_id AND i.published_at IS e.published_at AND i.revision_kind=e.revision_kind
            WHERE e.series_id=? AND e.definition_id=? AND e.source_id=? AND i.series_id=? AND i.definition_id=?
            AND e.value_decimal IS NOT NULL AND i.value_decimal IS NOT NULL AND e.period_end<=?
            ORDER BY e.period_end DESC LIMIT 1""",
            ("exports", definitions["exports"]["definition_id"], definitions["exports"]["source_id"],
             "imports", definitions["imports"]["definition_id"], cutoff)).fetchone()
        return row[0] if row else None

    def _points(self, connection, dependencies: tuple[str, ...], periods: set[str]) -> tuple[NormalizedObservation, ...]:
        points = []
        for sid in dependencies:
            definition = self.catalog["requirements"][sid]
            remaining = MAX_QUERY_ROWS - len(points)
            # Match the immutable identity index's period prefix. Ordering by
            # period_end instead makes SQLite scan the series archive; history
            # resolution below independently sorts publication/revision dates.
            rows = connection.execute("""SELECT * FROM observations WHERE series_id=? AND definition_id=? AND source_id=?
                AND period_id IN (SELECT value FROM json_each(?))
                ORDER BY period_id,vintage_id,parser_version LIMIT ?""",
                (sid, definition["definition_id"], definition["source_id"], json.dumps(sorted(periods)), remaining + 1)).fetchall()
            if len(rows) > remaining:
                raise QueryLimitExceeded("Requested history has too many revisions; narrow the window.")
            points.extend(observation_from_row(connection, row) for row in rows)
        return tuple(points)

    @staticmethod
    def _history(points, sid, window):
        batches = tuple(NormalizedBatch(source_id=p.sources[0].source_id, observations=(p,), coverage="release_only") for p in points)
        history = next(s for s in build_history(batches, window=window).series if s.series_id == sid)
        # Repository ingestion prevents these; damaged SQL must not pick an arbitrary winner.
        if history.reason_code in {"conflicting_source_revision", "source_revision_regressed"}:
            raise QueryIntegrityError(history.reason_code)
        return history

    def _series(self, connection, sid: str, window: int, selection: str | None, now: datetime) -> SeriesRead:
        definition = self.catalog["requirements"][sid]
        if definition["status"] == "blocked":
            if selection is not None:
                raise ValueError("Period selection is unavailable for a blocked definition.")
            history = self._history((), sid, window)
            return SeriesRead(history, None, None, unavailable_comparison(definition["reason_code"]))
        dependencies = tuple(definition["inputs"]) if definition["status"] == "derived" else (sid,)
        anchor = self._period(sid, selection) if selection is not None else None
        if anchor is not None and anchor.end > now.date():
            raise ValueError("Select a completed observation period.")
        cutoff = anchor.end.isoformat() if anchor else now.date().isoformat()
        newest = [self._latest_end(connection, dependency, cutoff) for dependency in dependencies]
        if anchor is None and any(newest):
            anchor = self._at_end(sid, max(end for end in newest if end is not None))
        if anchor is None:
            history = self._history((), sid, window)
            return SeriesRead(history, None, None, compare(None, ()))
        periods = {p.id for p in _periods(anchor, window)}
        valid_end = (self._latest_balance_end(connection, anchor.end.isoformat()) if sid == "trade_balance" else
                     self._latest_end(connection, sid, anchor.end.isoformat(), valid=True))
        if valid_end is not None:
            periods.add(self._at_end(sid, valid_end).id)
        points = self._points(connection, dependencies, periods)
        history = self._history(points, sid, window)
        latest_valid = next((p for p in reversed(history.observations) if p.value is not None), None)
        if latest_valid is not None and sid != "trade_balance":
            periods.add(_reference_period(latest_valid).id)
            points = self._points(connection, dependencies, periods)
            history = self._history(points, sid, window)
        selected = {p.observation_period.id: p for p in history.observations}
        known_gaps = {slot.period.id: slot.reason_code for slot in history.window if slot.reason_code}
        slots = []
        for period in _periods(anchor, window):
            point = selected.get(period.id)
            reason = point.reason_code if point else known_gaps.get(period.id, "historical_observation_unavailable")
            if point is None:
                unavailable = self.catalog["sources"][definition["source_id"]].get("history_unavailable", [])
                reason = next((entry["reason_code"] for entry in unavailable if entry["period"] == period.end.strftime("%Y-%m")), reason)
                if sid == "gdp_growth_india" and reason == "historical_observation_unavailable":
                    reason = "comparable_base_history_unverified"
            slots.append(HistorySlot(period=period, observation=point, reason_code=reason))
        reason = next((slot.reason_code for slot in reversed(slots) if slot.reason_code), None)
        status = "unavailable" if not any(slot.observation is not None and slot.observation.value is not None for slot in slots) else "partial" if reason else "available"
        fields = {name: getattr(history, name) for name in type(history).model_fields}
        fields.update(window=tuple(slots), latest=selected.get(anchor.id), status=status, reason_code=reason,
                      comparison=compare(selected.get(anchor.id), history.observations))
        history = HistoricalSeries(**fields)
        older_cutoff = (slots[0].period.start - timedelta(days=1)).isoformat()
        truncated = any(self._latest_end(connection, dependency, older_cutoff) for dependency in dependencies)
        return SeriesRead(history, anchor, latest_valid, compare(latest_valid, history.observations), history_truncated=truncated)

    def _selections(self, indicator: str, selections: Mapping[str, str] | None) -> dict[str, str]:
        if indicator not in self.panels:
            raise UnknownIndicator(indicator)
        allowed = {s["id"] for s in self.panels[indicator]["series"]}
        if selections is not None and (not isinstance(selections, Mapping) or set(selections) - allowed):
            raise ValueError("Period selections must belong to the requested panel's series.")
        if selections is not None and any(not isinstance(value, str) for value in selections.values()):
            raise ValueError("Selected periods require canonical string identifiers.")
        return dict(selections or {})

    def _indicator(self, connection, indicator: str, window: int, selections: dict[str, str], now: datetime) -> IndicatorRead:
        panel = self.panels[indicator]
        series = tuple(self._series(connection, s["id"], window, selections.get(s["id"]), now) for s in panel["series"])
        by_id = {s.history.series_id: s for s in series}
        summaries = []
        unbound = {(entry["indicator_id"], entry["summary_slot"]): entry["id"] for entry in self.inventory["unbound_requirements"]}
        for slot, sid in enumerate(panel["summaries"]):
            requirement = sid if sid is not None else unbound[(indicator, slot)]
            definition = self.catalog["requirements"][requirement]
            reading = by_id.get(sid)
            observation = reading.latest_valid if reading else None
            reason = definition.get("reason_code") if definition["status"] == "blocked" else (
                "current_observation_missing" if observation is None else
                "latest_period_observation_missing" if reading.history.latest is None or reading.history.latest.value is None else None)
            comparison = reading.comparison if reading else unavailable_comparison(reason)
            summaries.append(SummaryRead(slot, requirement, definition["definition_id"], definition["unit"], observation, comparison, reason))
        return IndicatorRead(indicator, series, tuple(summaries))

    def series(self, series_id: str, *, window: int = 5, end_period_id: str | None = None, now: datetime | None = None) -> SeriesRead:
        if series_id not in self.series_ids:
            raise UnknownSeries(series_id)
        now = self._options(window, now)
        with self.database.connection(read_only=True) as connection:
            version = self._begin(connection)
            return replace(self._series(connection, series_id, window, end_period_id, now),
                           source_states=self._states(connection), checkpoint_run_id=version)

    def indicator(self, indicator_id: str, *, window: int = 5, end_periods: Mapping[str, str] | None = None,
                  now: datetime | None = None) -> IndicatorRead:
        selections = self._selections(indicator_id, end_periods)
        now = self._options(window, now)
        with self.database.connection(read_only=True) as connection:
            version = self._begin(connection)
            return replace(self._indicator(connection, indicator_id, window, selections, now),
                           source_states=self._states(connection), checkpoint_run_id=version)

    def dashboard(self, *, window: int = 5, now: datetime | None = None) -> DashboardRead:
        now = self._options(window, now)
        with self.database.connection(read_only=True) as connection:
            version = self._begin(connection)
            states = self._states(connection)
            panels = tuple(replace(self._indicator(connection, indicator, window, {}, now), source_states=states,
                                   checkpoint_run_id=version) for indicator in self.panels)
            ticker = tuple(UnavailableRequirement(requirement_id=q["instrument_id"], reason_code=self.catalog["requirements"][q["instrument_id"]]["reason_code"])
                           for q in self.inventory["ticker"]["instruments"])
            return DashboardRead(version, panels, ticker, states)

    def ticker_version(self) -> str | None:
        """Current ticker is gated; read its committed version without querying macro history."""
        with self.database.connection(read_only=True) as connection:
            return self._begin(connection)
