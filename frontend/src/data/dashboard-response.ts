import type { IndicatorId } from "../dashboard-panels";
import type { DatePrecision, DecimalValue, SourceReference, Unit } from "../ui/types";
import type { DataStatus } from "./dashboard-contract";

// Draft wire projection for M4 acceptance. Runtime input remains unknown until validated.
// dashboard-contract.ts contains the normalized result, with an AsOfDate object.
export interface ResponsePeriod {
  id: string;
  label: string;
  basis: "calendar" | "fiscal";
}
export interface ResponseObservation {
  value: DecimalValue;
  unit: Unit;
  definition_id: string;
  observation_period: ResponsePeriod;
  as_of: string | null;
  as_of_precision?: DatePrecision | null;
  as_of_kind?: "observation" | "period_end" | null;
  sources: readonly SourceReference[];
  status: DataStatus;
  reason_code: string | null;
  retention_allowed: boolean;
}
export interface ResponseComparison {
  value: DecimalValue;
  unit: Unit;
  precision: number;
  reference_label: string;
  kind: "previous_period" | "previous_year" | "other_geography" | "policy_reference";
  reference_series_id: string;
  reference_period_id: string;
  verified: true;
}
export interface ResponseSeries {
  name: string;
  precision: number;
  latest: ResponseObservation;
  comparison: ResponseComparison | null;
  history: { status: DataStatus; points: readonly ResponseObservation[]; truncated: boolean };
  policy?: { applicable: boolean; valid_from: string; valid_to: string | null };
}
export interface ResponseChart {
  periods: readonly ResponsePeriod[];
  domain: readonly [string, string];
  ticks: readonly string[];
  unit: Unit;
  precision: number;
  annotation_precision: number;
}
export interface ResponsePanel {
  series: Readonly<Record<string, ResponseSeries>>;
  period_label?: string | null;
  chart?: ResponseChart | null;
}
export interface ResponseQuote extends ResponseObservation {
  unit: "index_points";
  instrument_id: string;
  name: string;
  change: DecimalValue;
  change_percent: DecimalValue;
  comparison_label: string | null;
  precision: number;
  market_status: "open" | "closed" | "unknown";
}
export interface DashboardResponseV1Draft {
  data: {
    panels: Partial<Record<IndicatorId, ResponsePanel>>;
    ticker: {
      status: DataStatus;
      cadence: "scheduled" | "delayed" | "unknown";
      cadence_label: string | null;
      items: readonly ResponseQuote[];
    };
  };
  meta: { api_version: "v1"; generated_at: string; version: string; partial: boolean };
}
