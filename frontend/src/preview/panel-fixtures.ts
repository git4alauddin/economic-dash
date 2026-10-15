import type { PanelChart, PanelPresentation, PlotSeries, SummaryDatum } from "../ui/panel-models";
import type { Unit } from "../ui/types";

// SYNTHETIC_PANEL_FIXTURES_ONLY — no observations, source decisions or policy claims.
const cyan = "#0fc1e3", orange = "#f3a611", green = "#35df28", yellow = "#f4e15c", blue = "#4a9cff";
const labels = ["2021", "2022", "2023", "2024", "2025"];
const summary = (label: string, value: string, unit: Unit, change: string): SummaryDatum => ({ label, value, unit, precision: unit === "usd_billion" || unit === "inr_crore" ? 1 : 2, comparison: { value: change, unit: unit === "percent_yoy" || unit === "percent_of_gdp" || unit === "percent" ? "percentage_points" : unit, precision: 1, referenceLabel: "vs 2024" } });
const series = (id: string, label: string, kind: PlotSeries["kind"], color: string, values: string[]): PlotSeries => ({ id, label, kind, color, values });
const chart = (unit: Unit, domain: [number, number], ticks: string[], entries: PlotSeries[], references?: PanelChart["references"]): PanelChart => ({ labels, unit, domain, ticks, series: entries, precision: 2, annotationPrecision: 1, references });
const model = (summaries: SummaryDatum[], history: PanelChart): PanelPresentation => ({ state: "fresh", summaries, chart: history, period: { label: "2021–2025 · synthetic", basis: "calendar" }, sources: [{ source_id: "synthetic", name: "Synthetic examples", url: "https://example.com/", is_nse: false }], asOf: { value: "2025", precision: "year", kind: "observation" } });

export const panelFixtures: readonly PanelPresentation[] = [
  model([summary("India", "7.1", "percent_yoy", "0.3"), summary("World", "3.4", "percent_yoy", "-0.2")], chart("percent_yoy", [0, 10], ["0", "2", "4", "6", "8", "10"], [
    series("gdp_growth_india", "India", "bar", cyan, ["8.1", "6.2", "8.4", "6.8", "7.1"]), series("gdp_growth_world", "World", "bar", orange, ["6.1", "4.2", "3.8", "3.6", "3.4"]),
  ])),
  model([summary("India (2025)", "74.2", "percent_of_gdp", "1.7"), summary("US (synthetic)", "98.4", "percent_of_gdp", "-0.9")], chart("percent_of_gdp", [50, 100], ["50", "60", "70", "80", "90", "100"], [
    series("debt_to_gdp_india", "India", "area", cyan, ["88.4", "76.5", "62.3", "72.5", "74.2"]),
  ])),
  model([summary("Exports", "382.9", "usd_billion", "12.9"), summary("Imports", "461.2", "usd_billion", "21.2")], chart("usd_billion", [-100, 500], ["-100", "0", "100", "200", "300", "400", "500"], [
    series("imports", "Imports", "bar", cyan, ["360", "400", "420", "440", "461.2"]), series("exports", "Exports", "bar", orange, ["290", "330", "355", "370", "382.9"]), series("trade_balance", "Trade balance", "line", green, ["-70", "-70", "-65", "-70", "-78.3"]),
  ])),
  model([summary("GST growth", "9.8", "percent_yoy", "1.0"), summary("Monthly avg growth", "5.4", "percent_yoy", "-0.2")], chart("percent_yoy", [0, 12], ["0", "2", "4", "6", "8", "10", "12"], [
    series("synthetic_gst_growth", "GST growth", "bar", cyan, ["9.1", "6.3", "9.5", "8.8", "9.8"]), series("synthetic_gst_average_growth", "Average growth", "line", yellow, ["3.2", "3.3", "5.1", "5.6", "5.4"]),
  ])),
  model([summary("Inflation Rate", "4.1", "percent_yoy", "-0.6"), summary("RBI Target (synthetic)", "4.5", "percent", "0")], chart("percent_yoy", [0, 10], ["0", "2", "4", "6", "8", "10"], [
    series("cpi_yoy", "Inflation", "line", cyan, ["6.4", "5.8", "3.3", "4.7", "4.1"]),
  ], [{ id: "synthetic_policy", label: "RBI reference (synthetic)", value: "4.5" }])),
  model([summary("Total Expenditure", "400", "inr_crore", "40"), summary("Capital Expenditure", "110", "inr_crore", "15")], chart("inr_crore", [0, 450], ["0", "90", "180", "270", "360", "450"], [
    series("expenditure_capital", "Capital Expenditure", "bar", orange, ["60", "74", "88", "95", "110"]), series("expenditure_revenue", "Revenue Expenditure", "bar", blue, ["210", "222", "248", "265", "290"]), series("expenditure_total", "Total", "total", blue, ["270", "296", "336", "360", "400"]),
  ])),
];
