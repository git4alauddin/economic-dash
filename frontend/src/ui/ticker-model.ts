import { formatDecimal, MISSING } from "./format";
import type { AsOfDate, DecimalValue, SourceReference, UiState } from "./types";

// Presentation contract only. M2.6/M4 bind validated backend responses to it.
export interface MarketQuote {
  instrumentId: string;
  label: string;
  state: UiState;
  value: DecimalValue;
  changePoints: DecimalValue;
  changePercent: DecimalValue;
  comparisonLabel: string | null;
  precision: number;
  asOf: AsOfDate | null;
  sources: readonly SourceReference[];
  detail?: string;
}

export interface TickerPresentation {
  state: UiState;
  refreshing: boolean;
  cadence: "scheduled" | "delayed" | "unknown";
  cadenceLabel: string | null;
  items: readonly MarketQuote[];
}

export function quoteIsVisible(model: TickerPresentation, quote: MarketQuote): boolean {
  return ["fresh", "stale"].includes(model.state) && ["fresh", "stale"].includes(quote.state);
}

export function tickerStatus(model: TickerPresentation): string {
  if (model.state === "loading") return "LOADING";
  if (model.state === "error") return "ERROR";
  const visible = model.items.filter((quote) => quoteIsVisible(model, quote) && formatDecimal(quote.value, quote.precision) !== MISSING);
  if (!visible.length) return "NO DATA";
  if (model.state === "stale" || visible.some((quote) => quote.state === "stale")) return "STALE";
  if (model.refreshing) return "UPDATING";
  return model.cadence === "scheduled" ? "SCHEDULED" : model.cadence === "delayed" ? "DELAYED" : "AVAILABLE";
}

// Instrument labels reserve space, without claiming approved source coverage.
export const unavailableTicker: TickerPresentation = {
  state: "unavailable", refreshing: false, cadence: "unknown", cadenceLabel: null,
  items: ["SENSEX", "NIFTY BANK", "NIFTY IT"].map((label) => ({
    instrumentId: label.toLowerCase().replaceAll(" ", "_"), label, state: "unavailable",
    value: null, changePoints: null, changePercent: null, comparisonLabel: null,
    precision: 2, asOf: null, sources: [],
  })),
};
