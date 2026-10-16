import { dashboardPanels } from "../dashboard-panels";
import { panelBindings, type DataStatus } from "../data/dashboard-contract";
import type { Unit } from "../ui/types";
import type { DashboardResponseFixture, ResponseObservation, ResponseQuote } from "./dashboard-response-fixture";
import { panelFixtures } from "./panel-fixtures";

// SYNTHETIC_API_STATE_FIXTURES_ONLY — deliberately synthetic preview input, never real observations.
export function dashboardFixture(retention = true) {
  const observation = (value: string | null, unit: Unit, year = "2025"): ResponseObservation => ({
    value, unit, status: "fresh" as DataStatus, definition_id: `synthetic_${unit}`,
    observation_period: { id: year, label: year, basis: "calendar" as const },
    as_of: year, as_of_precision: "year", as_of_kind: "observation",
    sources: [{ source_id: "synthetic_api", name: "Synthetic API examples", url: "https://example.com/api-fixture", is_nse: false }],
    retention_allowed: retention, reason_code: null as string | null,
  });
  const panels = Object.fromEntries(dashboardPanels.map((panel, index) => {
    const binding = panelBindings[panel.id], chart = panelFixtures[index].chart!;
    return [panel.id, {
      period_label: "2021–2025 · synthetic API", chart: { unit: binding.series[0].unit, domain: [String(chart.domain[0]), String(chart.domain[1])] as const, ticks: chart.ticks,
        periods: chart.labels.map((label) => ({ id: label, label, basis: "calendar" as const })), precision: 2, annotation_precision: 1 },
      series: Object.fromEntries(binding.series.map((definition, position) => {
        const original = chart.series[position], values = original?.values ?? chart.labels.map(() => "4.5");
        return [definition.id, { name: definition.label, precision: 2,
          latest: observation(definition.id === "rbi_target" ? "4.5" : values.at(-1)!, definition.unit), comparison: null,
          history: { status: "fresh" as DataStatus, points: values.map((value, point) => observation(value, definition.unit, chart.labels[point])), truncated: false },
          policy: definition.id === "rbi_target" ? { applicable: true, valid_from: "2021-01-01", valid_to: "2025-12-31" } : undefined,
        }];
      })),
    }];
  }));
  // Fixed bindings choose presentation roles; fixture values have no economic meaning.
  const quote: ResponseQuote = { ...observation("81234.56", "index_points"), unit: "index_points", instrument_id: "synthetic_sensex", name: "SENSEX",
    change: "0", change_percent: "0", comparison_label: "vs synthetic previous close", precision: 2, market_status: "closed" };
  return { data: { panels, ticker: { status: "fresh" as DataStatus, cadence: "scheduled", cadence_label: "Synthetic schedule: every 60 seconds", items: [quote] } },
    meta: { api_version: "v1", generated_at: "2025-01-03T12:00:00Z", version: "synthetic_snapshot_1", partial: false as boolean } } satisfies DashboardResponseFixture;
}

export const stateScenarioNames = ["fresh", "loading", "partial", "empty", "unavailable", "error", "retained", "no-retention", "mixed-retention", "malformed", "unauthorized", "dense"] as const;
export type StateScenario = typeof stateScenarioNames[number];
export function responseFixture(scenario: StateScenario) {
  const raw = dashboardFixture();
  if (scenario === "dense") {
    const panel = raw.data.panels.gdp_growth;
    panel.period_label = "1500–1999 · synthetic stress case";
    panel.chart.periods = Array.from({length:500},(_,index)=>({id:String(1500+index),label:String(1500+index),basis:"calendar"}));
    for (const series of Object.values(panel.series)) {
      const originals = series.history.points;
      series.history.points = panel.chart.periods.map((period,index)=>({...originals[index%originals.length],observation_period:{...period,basis:"calendar"},as_of:period.id}));
    }
  }
  if (scenario === "partial") {
    raw.data.panels.gdp_growth.series.gdp_growth_world.latest.value = "NaN";
    raw.meta.partial = true;
  }
  if (scenario === "empty" || scenario === "unavailable") {
    for (const panel of Object.values(raw.data.panels)) for (const series of Object.values(panel.series)) {
      series.latest.value = null; series.latest.status = scenario;
      series.history.points = []; series.history.status = scenario;
    }
    raw.data.ticker.status = scenario;
    raw.data.ticker.items = [];
  }
  return raw;
}
