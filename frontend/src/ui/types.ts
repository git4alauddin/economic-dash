// Presentation inputs, not final API models. M2.6 adapts M4's validated responses.
export type DecimalValue = string | null;
export type Unit = "percent_yoy" | "percent_of_gdp" | "percent" | "percentage_points" | "inr_crore" | "usd_billion" | "index_points";
export type DatePrecision = "year" | "month" | "day" | "instant";
export type UiState = "loading" | "fresh" | "stale" | "empty" | "error" | "unavailable";

export interface AsOfDate {
  value: string | null;
  precision: DatePrecision;
  kind: "observation" | "period_end";
}

export interface SourceReference {
  source_id: string;
  name: string;
  url: string;
  is_nse: boolean;
}
