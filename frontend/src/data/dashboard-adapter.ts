import { dashboardPanels } from "../dashboard-panels";
import { formatDate, MISSING, toChartNumber } from "../ui/format";
import type { PanelChart, PanelPresentation } from "../ui/panel-models";
import type { MarketQuote, TickerPresentation } from "../ui/ticker-model";
import type { AsOfDate, SourceReference, UiState } from "../ui/types";
import { panelBindings, type ApiSeries, type DashboardSnapshot, type Observation } from "./dashboard-contract";
import * as v from "./validate";

const displayable = (state: UiState) => state === "fresh" || state === "stale";
function aggregate(states: readonly UiState[]): UiState {
  if (states.includes("stale")) return "stale";
  if (states.includes("fresh")) return "fresh";
  if (states.includes("error")) return "error";
  if (states.length && states.every((state) => state === "empty")) return "empty";
  return "unavailable";
}
function mergeSources(observations: readonly Observation[]): SourceReference[] {
  return [...new Map(observations.flatMap((point) => point.sources).map((source) => [source.source_id, source])).values()];
}
function sharedDate(observations: readonly Observation[]): AsOfDate | null {
  const dates = observations.filter((point) => point.value !== null).map((point) => point.as_of);
  return dates.length && dates.every((date) => JSON.stringify(date) === JSON.stringify(dates[0])) ? dates[0] : null;
}
export function stateDetail(state: UiState, reason: string | null): string {
  if (reason === "refresh_failed") return "Refresh failed; permitted observations retained and marked stale.";
  if (reason === "invalid_response") return "Response validation failed; no unvalidated values are shown.";
  if (state === "stale") return "Retained observation; check its original date and source.";
  if (state === "error") return "Unable to load this data.";
  if (state === "empty") return "No observations in the supported period.";
  if (state === "unavailable") return "No validated observation available.";
  return "Observation date and collection freshness are independent.";
}

function chartModel(raw: unknown, entries: Readonly<Record<string, ApiSeries>>, panelId: string): PanelChart | null {
  try {
    const input = v.record(raw), unit = v.unit(input.unit), domain = v.list(input.domain, 2).map((value) => toChartNumber(v.decimal(value)));
    if (domain.length !== 2 || domain[0] === null || domain[1] === null || domain[0] >= domain[1]) throw new v.ContractError();
    const periods = v.list(input.periods).map((value) => {
      const item = v.record(value);
      if (typeof item.basis !== "string" || !["calendar", "fiscal"].includes(item.basis)) throw new v.ContractError();
      return { id: v.text(item.id), label: v.text(item.label), basis: item.basis as "calendar" | "fiscal" };
    });
    if (!periods.length || new Set(periods.map((period) => period.id)).size !== periods.length || periods.some((period) => period.basis !== periods[0].basis)) throw new v.ContractError();
    const ticks = v.list(input.ticks, 20).map((value) => { const tick = v.decimal(value), number = toChartNumber(tick); if (tick === null || number === null || number < domain[0]! || number > domain[1]!) throw new v.ContractError(); return tick; });
    if (ticks.length < 2) throw new v.ContractError();
    const plots = panelBindings[panelId].series.filter((binding) => binding.id !== "rbi_target").map((binding) => {
      if (binding.unit !== unit) throw new v.ContractError();
      const history = entries[binding.id]?.history;
      return { id: binding.id, label: entries[binding.id]?.name ?? binding.label, kind: binding.kind, color: binding.color,
        values: periods.map((period) => {
          const point = history?.points.find((candidate) => candidate.observation_period.id === period.id);
          return point && displayable(history!.status) && displayable(point.status) && point.observation_period.basis === period.basis && point.observation_period.label === period.label ? point.value : null;
        }) };
    });
    const policy = entries.rbi_target;
    const reference = policy?.policy?.applicable && displayable(policy.latest.status) && policy.latest.value !== null ? [{ id: "rbi_target", label: policy.name, value: policy.latest.value }] : [];
    return { periods, labels: periods.map((period) => period.label), domain: domain as [number, number], ticks, unit,
      precision: v.precision(input.precision), annotationPrecision: v.precision(input.annotation_precision), series: plots, references: reference };
  } catch { return null; }
}

export function adaptPanel(panelId: string, raw: unknown, entries: Readonly<Record<string, ApiSeries>>, validatedChart?: PanelChart | null): PanelPresentation {
  const binding = panelBindings[panelId], items = Object.values(entries), latest = items.map((item) => item.latest);
  let input: Record<string, unknown> = {};
  try { input = v.record(raw); } catch { /* Missing panel is explicitly unavailable. */ }
  const chart = validatedChart === undefined ? chartModel(input.chart, entries, panelId) : validatedChart;
  const chartStates = items.filter((item) => item.history.points.some((point) => point.value !== null)).map((item) => item.history.status);
  const chartState = chart ? aggregate(chartStates.length ? chartStates : items.map((item) => item.history.status)) : aggregate(items.map((item) => item.history.status)) === "empty" ? "empty" : "unavailable";
  const state = aggregate([...latest.map((point) => point.status), chartState]);
  const summaries = binding.summaries.map((id) => {
    const item = id ? entries[id] : undefined, definition = binding.series.find((entry) => entry.id === id);
    return { label: item?.name ?? definition?.label ?? "Comparison unavailable", value: item?.latest.value ?? null,
      unit: definition?.unit ?? binding.series[0].unit, precision: item?.precision ?? 2, state: item?.latest.status ?? "unavailable" as UiState,
      comparison: item?.comparison && item.latest.value !== null ? { value: item.comparison.value, unit: item.comparison.unit, precision: item.comparison.precision, referenceLabel: item.comparison.reference_label } : undefined };
  });
  const partial = binding.series.some((entry) => !entries[entry.id] || entries[entry.id].latest.value === null || !displayable(entries[entry.id].history.status));
  const allPoints = [...latest, ...items.flatMap((item) => item.history.points)];
  return { state, chartState, summaries, chart, period: { label: typeof input.period_label === "string" ? input.period_label.slice(0, 240) : null },
    sources: mergeSources(allPoints), asOf: sharedDate(latest),
    detail: partial && displayable(state) ? "Partial data · inspect series details" : stateDetail(state, latest.find((point) => point.reason_code)?.reason_code ?? null),
    seriesDetails: binding.series.map((definition) => {
      const item = entries[definition.id];
      return { id: definition.id, label: item?.name ?? definition.label, state: item?.latest.status ?? "unavailable",
        detail: item ? `${stateDetail(item.latest.status, item.latest.reason_code)} History: ${item.history.status}${item.history.truncated ? " · truncated" : ""}.${item.policy ? ` Policy validity: ${item.policy.valid_from} to ${item.policy.valid_to ?? "unspecified end"}.` : ""} ${(item.validationIssues ?? []).join(" ")}` : "No validated observation available.",
        sources: item ? mergeSources([item.latest, ...item.history.points]) : [], asOf: item?.latest.as_of ?? null,
        precision: item?.precision, history: item?.history.points.map((point) => ({ period: point.observation_period.label, value: point.value, unit: point.unit })) };
    }) };
}

function parseTicker(raw: unknown, issues: string[]): { model: TickerPresentation; retention: Record<string, boolean> } {
  const retention: Record<string, boolean> = {}, items: MarketQuote[] = [];
  try {
    const input = v.record(raw), status = v.status(input.status);
    for (const item of v.list(input.items, 100)) {
      try {
        const quote = v.record(item), point = v.observation(quote, "index_points"), id = v.text(quote.instrument_id);
        if (items.some((entry) => entry.instrumentId === id)) throw new v.ContractError();
        if (typeof quote.market_status !== "string" || !["open", "closed", "unknown"].includes(quote.market_status)) throw new v.ContractError();
        const comparisonLabel = quote.comparison_label === null ? null : v.text(quote.comparison_label);
        const change = v.decimal(quote.change), percent = v.decimal(quote.change_percent);
        if ((change !== null || percent !== null) && !comparisonLabel) throw new v.ContractError();
        items.push({ instrumentId: id, label: v.text(quote.name), value: displayable(status) ? point.value : null, state: displayable(status) ? point.status : status,
          changePoints: displayable(status) ? change : null, changePercent: displayable(status) ? percent : null, comparisonLabel, precision: v.precision(quote.precision), asOf: point.as_of, sources: point.sources,
          detail: stateDetail(point.status, point.reason_code) });
        retention[id] = displayable(status) && point.retention_allowed;
      } catch { issues.push("ticker: invalid instrument omitted"); }
    }
    if (typeof input.cadence !== "string" || !["scheduled", "delayed", "unknown"].includes(input.cadence)) throw new v.ContractError();
    return { model: { state: status, refreshing: false, cadence: input.cadence as TickerPresentation["cadence"], cadenceLabel: input.cadence_label === null ? null : v.text(input.cadence_label), items }, retention };
  } catch { issues.push("ticker: unavailable"); return { model: { state: "unavailable", refreshing: false, cadence: "unknown", cadenceLabel: null, items: [] }, retention: {} }; }
}

export function adaptDashboard(payload: unknown): DashboardSnapshot {
  const envelope = v.record(payload), data = v.record(envelope.data), meta = v.record(envelope.meta);
  if (meta.api_version !== "v1" || formatDate(v.text(meta.generated_at), "instant") === MISSING) throw new v.ContractError();
  const version = v.text(meta.version), issues: string[] = [], panels: Record<string, PanelPresentation> = {}, observations: Record<string, Record<string, ApiSeries>> = {};
  const panelData = v.record(data.panels);
  for (const panel of dashboardPanels) {
    const parsed: Record<string, ApiSeries> = {};
    let entries: Record<string, unknown> = {};
    try { entries = v.record(v.record(panelData[panel.id]).series); } catch { issues.push(`${panel.id}: unavailable`); }
    for (const binding of panelBindings[panel.id].series) {
      if (!Object.hasOwn(entries, binding.id)) { issues.push(`${panel.id}/${binding.id}: unavailable`); continue; }
      try {
        const item = v.series(entries[binding.id], binding.unit);
        if (binding.id === "rbi_target" && !item.policy?.applicable) throw new v.ContractError();
        parsed[binding.id] = item;
        if (item.history.status === "error" || item.latest.value === null || !displayable(item.latest.status) || item.validationIssues?.length) issues.push(`${panel.id}/${binding.id}: partial`);
      } catch { issues.push(`${panel.id}/${binding.id}: invalid series`); }
    }
    observations[panel.id] = parsed;
    panels[panel.id] = adaptPanel(panel.id, panelData[panel.id], parsed);
    if (!panels[panel.id].chart && Object.values(parsed).some((item) => item.history.points.some((point) => point.value !== null))) issues.push(`${panel.id}: invalid chart projection`);
  }
  const ticker = parseTicker(data.ticker, issues);
  return { panels, ticker: ticker.model, quoteRetention: ticker.retention, observations, version, generatedAt: meta.generated_at as string,
    partial: v.flag(meta.partial) || issues.length > 0, issues };
}
