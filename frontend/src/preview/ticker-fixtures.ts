import type { TickerPresentation } from "../ui/ticker-model";

// SYNTHETIC_TICKER_FIXTURES_ONLY — never market observations or source approvals.
export const tickerFixture: TickerPresentation = {
  state: "fresh", refreshing: false, cadence: "scheduled", cadenceLabel: "Synthetic schedule: every 60 seconds; not tick-by-tick",
  items: [
    { instrumentId: "synthetic_sensex", label: "SENSEX", value: "81234.56", changePoints: "321.12", changePercent: "0.40" },
    { instrumentId: "synthetic_bank", label: "NIFTY BANK", value: "52123.45", changePoints: "-135.60", changePercent: "-0.26" },
    { instrumentId: "synthetic_it", label: "NIFTY IT", value: "0", changePoints: "0", changePercent: "0" },
  ].map((quote) => ({ ...quote, state: "fresh", precision: 2, comparisonLabel: "vs synthetic previous close",
    sources: [{ source_id: "synthetic_market", name: "Synthetic market examples", url: "https://example.com/market-fixture", is_nse: false }],
    asOf: { value: "2025-01-02T10:30:00Z", precision: "instant", kind: "observation" },
  })),
};

export const tickerScenarios: Record<string, TickerPresentation> = {
  scheduled: tickerFixture,
  delayed: { ...tickerFixture, cadence: "delayed", cadenceLabel: "Synthetic delayed snapshot; delay supplied by provider" },
  updating: { ...tickerFixture, refreshing: true },
  stale: { ...tickerFixture, state: "stale" },
  partial: { ...tickerFixture, items: tickerFixture.items.map((quote, index) => index === 1 ? { ...quote, state: "unavailable", value: null, changePoints: null, changePercent: null, asOf: null, sources: [] } : quote) },
  loading: { ...tickerFixture, state: "loading", cadenceLabel: null },
  error: { ...tickerFixture, state: "error", cadenceLabel: null },
  empty: { ...tickerFixture, state: "empty", items: [], cadenceLabel: null },
  unavailable: { ...tickerFixture, state: "unavailable", cadenceLabel: null },
};
