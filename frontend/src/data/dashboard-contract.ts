import type { PanelPresentation, PlotSeries } from "../ui/panel-models";
import type { TickerPresentation } from "../ui/ticker-model";
import type { AsOfDate, DecimalValue, SourceReference, UiState, Unit } from "../ui/types";

// Validated/normalized display models; public v1 wire fields live in dashboard-response.ts.
// M4 acceptance checks SQL/API payloads against this adapter and the panel bindings.
export type DataStatus = Exclude<UiState, "loading">;
export interface Observation {
  value: DecimalValue;
  unit: Unit;
  definition_id: string;
  observation_period: { id: string; label: string; basis: "calendar" | "fiscal" } | null;
  as_of: AsOfDate | null;
  sources: readonly SourceReference[];
  status: DataStatus;
  reason_code: string | null;
  retention_allowed: boolean;
}
export interface ApiSeries {
  name: string;
  precision: number;
  latest: Observation;
  comparison: { value: DecimalValue; unit: Unit; precision: number; reference_label: string; kind: string; reference_series_id: string; reference_period_id: string } | null;
  comparisonReason?: string | null;
  history: { status: DataStatus; points: readonly Observation[]; truncated: boolean };
  policy?: { applicable: boolean; valid_from: string; valid_to: string | null };
  validationIssues?: readonly string[];
}
export interface SeriesBinding { id: string; label: string; unit: Unit; kind: PlotSeries["kind"]; color: string; }
export interface PanelBinding { summaries: readonly [string, string | null]; series: readonly SeriesBinding[]; }
export interface DashboardSnapshot {
  panels: Readonly<Record<string, PanelPresentation>>;
  ticker: TickerPresentation;
  version: string;
  generatedAt: string;
  partial: boolean;
  issues: readonly string[];
  // Parsed observations are the sole memory cache; no storage/persistence here.
  observations: Readonly<Record<string, Readonly<Record<string, ApiSeries>>>>;
  quoteRetention: Readonly<Record<string, boolean>>;
}

const entry = (id: string, label: string, unit: Unit, kind: PlotSeries["kind"], color: string): SeriesBinding => ({ id, label, unit, kind, color });
export const panelBindings: Readonly<Record<string, PanelBinding>> = {
  gdp_growth: { summaries: ["gdp_growth_india", "gdp_growth_world"], series: [entry("gdp_growth_india", "India", "percent_yoy", "bar", "#0fc1e3"), entry("gdp_growth_world", "World", "percent_yoy", "bar", "#f3a611")] },
  debt_to_gdp: { summaries: ["debt_to_gdp_india", null], series: [entry("debt_to_gdp_india", "India", "percent_of_gdp", "area", "#0fc1e3")] },
  trade: { summaries: ["exports", "imports"], series: [entry("imports", "Imports", "usd_billion", "bar", "#0fc1e3"), entry("exports", "Exports", "usd_billion", "bar", "#f3a611"), entry("trade_balance", "Trade balance", "usd_billion", "line", "#35df28")] },
  gst_collection: { summaries: ["gst_total", "gst_monthly_average"], series: [entry("gst_total", "GST Collections", "inr_crore", "bar", "#0fc1e3"), entry("gst_monthly_average", "Monthly Average", "inr_crore", "line", "#f4e15c")] },
  inflation_india: { summaries: ["cpi_yoy", "rbi_target"], series: [entry("cpi_yoy", "Inflation Rate", "percent_yoy", "line", "#0fc1e3"), entry("rbi_target", "RBI Target", "percent", "line", "#f4e15c")] },
  government_expenditure: { summaries: ["expenditure_total", "expenditure_capital"], series: [entry("expenditure_capital", "Capital Expenditure", "inr_crore", "bar", "#f3a611"), entry("expenditure_revenue", "Revenue Expenditure", "inr_crore", "bar", "#4a9cff"), entry("expenditure_total", "Total Expenditure", "inr_crore", "total", "#f4e15c")] },
};
