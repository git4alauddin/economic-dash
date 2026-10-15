import type { AsOfDate, DecimalValue, SourceReference, UiState, Unit } from "./types";

// Frontend presentation models. Final API responses are adapted in M2.6.
export interface SummaryDatum {
  label: string; value: DecimalValue; unit: Unit; precision: number;
  comparison?: { value: DecimalValue; unit: Unit; precision: number; referenceLabel: string };
}
export interface PlotSeries {
  id: string; label: string; values: readonly DecimalValue[]; color: string;
  kind: "bar" | "line" | "area" | "total";
}
export interface PanelChart {
  labels: readonly string[];
  domain: readonly [number, number];
  ticks: readonly string[];
  unit: Unit;
  precision: number;
  annotationPrecision: number;
  series: readonly PlotSeries[];
  references?: readonly { id: string; label: string; value: DecimalValue }[];
}
export interface PanelPresentation {
  state: UiState;
  summaries: readonly SummaryDatum[];
  period: { label: string | null; basis?: "calendar" | "fiscal" };
  chart: PanelChart | null;
  sources: readonly SourceReference[];
  asOf: AsOfDate | null;
}
