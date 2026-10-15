import { adaptDashboard, adaptPanel } from "./dashboard-adapter";
import type { ApiSeries, DashboardSnapshot, Observation } from "./dashboard-contract";
import type { PanelPresentation } from "../ui/panel-models";

export interface DashboardView {
  phase: "loading" | "ready" | "error";
  snapshot: DashboardSnapshot | null;
  message: string;
}
export const initialDashboardView: DashboardView = { phase: "loading", snapshot: null, message: "Loading dashboard…" };
export function beginRefresh(previous: DashboardSnapshot | null): DashboardView {
  return previous ? { phase: "ready", snapshot: { ...previous, ticker: { ...previous.ticker, refreshing: true } }, message: "Refreshing dashboard…" } : initialDashboardView;
}
export function acceptDashboard(payload: unknown): DashboardView {
  const snapshot = adaptDashboard(payload);
  return { phase: "ready", snapshot, message: snapshot.partial ? "Dashboard loaded with partial or unavailable data." : "Dashboard loaded." };
}

const mayRetain = (point: Observation) => point.retention_allowed && point.value !== null && ["fresh", "stale"].includes(point.status);
function retain(point: Observation): Observation {
  return { ...point, value: mayRetain(point) ? point.value : null, status: mayRetain(point) ? "stale" : "unavailable", reason_code: "refresh_failed" };
}
export function failDashboard(previous: DashboardSnapshot | null, kind: "network" | "invalid" | "unauthorized"): DashboardView {
  if (!previous || kind === "unauthorized") return { phase: "error", snapshot: null, message: kind === "unauthorized" ? "Sign in is required to view dashboard data." : kind === "invalid" ? "Unable to validate the dashboard response." : "Unable to load dashboard data." };
  const observations: Record<string, Record<string, ApiSeries>> = {}, panels: Record<string, PanelPresentation> = {};
  for (const [id, entries] of Object.entries(previous.observations)) {
    observations[id] = Object.fromEntries(Object.entries(entries).map(([key, item]) => {
      const latest = retain(item.latest), points = item.history.points.map(retain);
      return [key, { ...item, latest, comparison: latest.value === null ? null : item.comparison,
        history: { ...item.history, points, status: points.some((point) => point.value !== null) ? "stale" : "error" } } satisfies ApiSeries];
    }));
    const old = previous.panels[id], chart = old.chart ? { ...old.chart,
      series: old.chart.series.map((series) => ({ ...series, values: series.values.map((value, index) => {
        const point = entries[series.id]?.history.points.find((candidate) => candidate.observation_period.id === old.chart?.periods?.[index]?.id);
        return point && mayRetain(point) ? value : null;
      }) })),
      references: observations[id].rbi_target?.latest.value !== null && observations[id].rbi_target?.latest.value !== undefined ? old.chart.references : [],
    } : null;
    panels[id] = adaptPanel(id, { period_label: old.period.label }, observations[id], chart);
    panels[id] = { ...panels[id], detail: kind === "invalid" ? "Response validation failed; permitted observations retained as stale." : "Refresh failed; only permitted observations retained as stale." };
  }
  const items = previous.ticker.items.map((item) => {
    const allowed = previous.quoteRetention[item.instrumentId] === true && item.value !== null && ["fresh", "stale"].includes(item.state);
    return { ...item, state: allowed ? "stale" as const : "unavailable" as const, value: allowed ? item.value : null,
      changePoints: allowed ? item.changePoints : null, changePercent: allowed ? item.changePercent : null, detail: allowed ? "Refresh failed; permitted observation retained as stale." : "Refresh failed; retention not permitted." };
  });
  return { phase: "ready", snapshot: { ...previous, observations, panels, partial: true,
    ticker: { ...previous.ticker, state: items.some((item) => item.value !== null) ? "stale" : "error", refreshing: false, items },
    issues: [...previous.issues, `refresh: ${kind}`] }, message: "Refresh failed. Retained values are marked stale; other values are unavailable." };
}
