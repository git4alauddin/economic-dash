"""SQL read results -> public v1 models; explicit display rounding only."""

from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext

from app.api_models import (
    CatalogIndicator, CatalogSeries, DashboardData, Envelope, HistoryData, ResponseChart, ResponseComparison,
    ResponseHistory, ResponseMeta, ResponseObservation, ResponsePanel, ResponsePeriod, ResponseQuote,
    ResponseSeries, ResponseSummary, ResponseTicker,
)
from app.collectors.freshness import SourceState, freshness
from app.queries import DashboardQueries, DashboardRead, IndicatorRead, SeriesRead

NAMES = {"gdp_growth_india": "India", "gdp_growth_world": "World", "debt_to_gdp_india": "India",
         "imports": "Imports", "exports": "Exports", "trade_balance": "Trade balance", "gst_total": "GST Collections",
         "gst_monthly_average": "Monthly Average", "cpi_yoy": "Inflation Rate", "rbi_target": "RBI Target",
         "expenditure_capital": "Capital Expenditure", "expenditure_revenue": "Revenue Expenditure", "expenditure_total": "Total Expenditure"}


def period(value):
    return ResponsePeriod(**value.model_dump()) if value else None


def comparison(value):
    if value.value is None:
        return None
    return ResponseComparison(value=value.value.display_decimal(2), unit=value.unit, precision=2,
        reference_label=value.reference.observation_period.label,
        kind="previous_period" if value.current.series_id == "cpi_yoy" else "previous_year",
        reference_series_id=value.reference.series_id, reference_period_id=value.reference_period_id,
        transform_id=value.transform_id, exact_numerator=str(value.value.numerator), exact_denominator=str(value.value.denominator))


def observation(queries, sid, point, states, now, *, selected=None, reason=None):
    definition = queries.catalog["requirements"][sid]
    state = next((s for s in states if s.source_id == definition["source_id"]), SourceState(source_id=definition["source_id"]))
    blocked = definition.get("reason_code") if definition["status"] == "blocked" else None
    validity = freshness(sid, point, state, now, blocked_reason=blocked, empty=state.outcome == "empty")
    status, code = validity.status, validity.reason_code
    if point is None or point.value is None:
        code = blocked or reason or code
    elif reason:
        status, code = "stale", reason
    fields = dict(value=format(point.value, "f") if point is not None and point.value is not None else None,
        unit=definition["unit"], definition_id=definition["definition_id"],
        observation_period=period(point.observation_period if point else selected), as_of=point.as_of if point else None,
        as_of_precision=point.as_of_precision if point else None, as_of_kind=point.as_of_kind if point else None,
        sources=point.sources if point else (), status=status, reason_code=code, retention_allowed=validity.retention_allowed)
    if point:
        fields.update({key: getattr(point, key) for key in ("published_at", "retrieved_at", "dataset_updated_at", "revision_kind", "vintage_id", "parser_version", "normalization_id", "transform_id", "inputs")})
    return ResponseObservation(**fields)


def series(queries: DashboardQueries, value: SeriesRead, states, now: datetime) -> ResponseSeries:
    sid = value.history.series_id
    retained = value.latest_valid is not None and (value.history.latest is None or value.history.latest.value is None)
    latest = observation(queries, sid, value.latest_valid, states, now, selected=value.selected_period,
                         reason="latest_period_observation_missing" if retained else value.history.reason_code if value.latest_valid is None else None)
    points = tuple(observation(queries, sid, slot.observation, states, now, selected=slot.period, reason=slot.reason_code)
                   for slot in value.history.window)
    displayable = [point for point in points if point.value is not None]
    status = "stale" if any(p.status == "stale" for p in displayable) else "fresh" if displayable else "unavailable"
    # A bounded window is explicit; neither omitted archive nor revisions are lost.
    return ResponseSeries(name=NAMES[sid], latest=latest, comparison=comparison(value.comparison),
        comparison_reason_code=value.comparison.reason_code,
        history=ResponseHistory(status=status, points=points, truncated=value.history_truncated))


def chart(value: IndicatorRead, entries: dict[str, ResponseSeries]):
    plotted = [s for s in value.series if s.history.series_id != "rbi_target"]
    slots = {slot.period.id: slot.period for s in plotted for slot in s.history.window}
    values = [Decimal(p.value) for s in plotted for p in entries[s.history.series_id].history.points if p.value is not None]
    if not slots or not values:
        return None
    with localcontext() as context:
        context.prec = 80
        low, high = min(Decimal(0), min(values)), max(Decimal(0), max(values))
        if low == high:
            high = low + 1
        rough = (high - low) / 4
        scale = Decimal(10) ** rough.adjusted()
        step = next(Decimal(n) * scale for n in (1, 2, 5, 10) if Decimal(n) * scale >= rough)
        lower = (low / step).to_integral_value(rounding=ROUND_FLOOR) * step
        upper = (high / step).to_integral_value(rounding=ROUND_CEILING) * step
        ticks = tuple(format(lower + step * index, "f") for index in range(int((upper - lower) / step) + 1))
    return ResponseChart(periods=tuple(period(p) for p in sorted(slots.values(), key=lambda p: (p.end, p.id))),
        domain=(format(lower, "f"), format(upper, "f")), ticks=ticks, unit=entries[plotted[0].history.series_id].latest.unit)


def panel(queries: DashboardQueries, value: IndicatorRead, now: datetime) -> ResponsePanel:
    entries = {s.history.series_id: series(queries, s, value.source_states, now) for s in value.series}
    summaries = []
    for card in value.summaries:
        point = observation(queries, card.requirement_id, card.observation, value.source_states, now, reason=card.reason_code) if card.definition_id is not None and card.unit is not None else None
        summaries.append(ResponseSummary(slot=card.slot, requirement_id=card.requirement_id, definition_id=card.definition_id,
            unit=card.unit, observation=point, comparison=comparison(card.comparison), comparison_reason_code=card.comparison.reason_code, reason_code=card.reason_code))
    latest = [entry.latest for entry in entries.values() if entry.latest.value is not None]
    labels = {p.observation_period.label for p in latest}
    label = next(iter(labels)) if len(labels) == 1 else " | ".join(f"{name}: {entry.latest.observation_period.label} ({entry.latest.observation_period.basis})"
        for name, entry in ((entry.name, entry) for entry in entries.values()) if entry.latest.value is not None) if latest else None
    return ResponsePanel(indicator_id=value.indicator_id, series=entries, summaries=tuple(summaries), period_label=label, chart=chart(value, entries))


def ticker(queries):
    return ResponseTicker(items=tuple(ResponseQuote(instrument_id=item["instrument_id"], name=item["label"], value=None,
        definition_id=queries.catalog["requirements"][item["instrument_id"]]["definition_id"], observation_period=None,
        as_of=None, as_of_precision=None, as_of_kind=None, sources=(), status="unavailable",
        reason_code=queries.catalog["requirements"][item["instrument_id"]]["reason_code"], retention_allowed=False)
        for item in queries.inventory["ticker"]["instruments"]))


def meta(version, now, partial=True):
    return ResponseMeta(generated_at=now, version=version or "empty", partial=partial)


def dashboard(queries, value: DashboardRead, now):
    panels = {p.indicator_id: panel(queries, p, now) for p in value.panels}
    return Envelope[DashboardData](data=DashboardData(panels=panels, ticker=ticker(queries)),
                                   meta=meta(value.checkpoint_run_id, now))


def history(queries, value: SeriesRead, now):
    wire = series(queries, value, value.source_states, now)
    return Envelope[HistoryData](data=HistoryData(indicator_id=value.history.indicator_id, series_id=value.history.series_id,
        selected_period=period(value.selected_period), series=wire, superseded=value.history.superseded),
        meta=meta(value.checkpoint_run_id, now, value.history.status != "available" or wire.latest.status != "fresh"))


def catalog(queries, value: DashboardRead, now):
    indicators = []
    for p in value.panels:
        entries = []
        for s in p.series:
            sid = s.history.series_id
            definition = queries.catalog["requirements"][sid]
            source = queries.catalog["sources"][definition["source_id"]]
            entries.append(CatalogSeries(series_id=sid, name=NAMES[sid], definition_id=definition["definition_id"],
                definition=definition["definition"], unit=definition["unit"], frequency=definition["frequency"], basis=definition["basis"],
                status=definition["status"], reason_code=definition.get("reason_code"), source_id=definition["source_id"],
                limitations=(source["limits"], queries.catalog["reuse"][source["reuse_id"]]["constraint"]),
                available_periods=tuple(period(slot.period) for slot in s.history.window if slot.observation is not None and slot.observation.value is not None)))
        indicators.append(CatalogIndicator(indicator_id=p.indicator_id, series=tuple(entries), summary_requirements=tuple(c.requirement_id for c in p.summaries)))
    return Envelope[tuple[CatalogIndicator, ...]](data=tuple(indicators), meta=meta(value.checkpoint_run_id, now))
