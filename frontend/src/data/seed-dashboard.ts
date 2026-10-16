// Deliberately illustrative presentation data, available only through Seed mode.
// This module never writes observations, supplies API fallbacks or claims a publisher.
import type { DashboardView } from "./dashboard-state";
import type { PanelChart, PanelPresentation, PlotSeries, SummaryDatum } from "../ui/panel-models";
import type { Unit } from "../ui/types";

const sampleSource = { source_id: "seed_demo", name: "Seed sample", url: "", is_nse: false };
const annual = ["2021", "2022", "2023", "2024", "2025"];
const fiscal = ["FY2021–22", "FY2022–23", "FY2023–24", "FY2024–25", "FY2025–26"];
const monthly = ["May 2026", "Jun 2026", "Jul 2026", "Aug 2026", "Sep 2026"];
const cyan = "#0fc1e3", orange = "#f3a611", green = "#35df28", yellow = "#f4e15c", blue = "#4a9cff";
const plot = (id: string, label: string, kind: PlotSeries["kind"], color: string, values: string[]): PlotSeries => ({ id, label, kind, color, values });
const change = (value: string, unit: Unit, referenceLabel: string): SummaryDatum["comparison"] => ({ value, unit, precision: 2, referenceLabel });
const summary = (label: string, value: string, unit: Unit, comparison?: SummaryDatum["comparison"]): SummaryDatum => ({ label, value, unit, precision: 2, state: "fresh", comparison });
function panel(summaries: SummaryDatum[], chart: PanelChart, period: string): PanelPresentation {
  return { state: "fresh", chartState: "fresh", partial: false, summaries, chart,
    period: { label: period }, sources: [sampleSource], asOf: null,
    detail: "Seed sample · illustrative values, not live observations.",
    seriesDetails: chart.series.map((series) => ({ id: series.id, label: series.label, state: "fresh",
      detail: "Illustrative seed history. Values and periods demonstrate the layout; no publisher is claimed.",
      sources: [sampleSource], asOf: null, precision: 2,
      history: series.values.map((value, index) => ({ period: chart.labels[index], value, unit: chart.unit })) })),
  };
}
const chart = (labels: string[], unit: Unit, domain: [number, number], ticks: string[], series: PlotSeries[], references?: PanelChart["references"]): PanelChart =>
  ({ labels: [...labels], unit, domain, ticks, series, references, precision: 2, annotationPrecision: 1 });

export function createSeedDashboard(): DashboardView {
  const panels: Record<string, PanelPresentation> = {
    gdp_growth: panel([summary("India", "7.1", "percent_yoy", change("0.30", "percentage_points", "vs 2024")),
      summary("World", "3.4", "percent_yoy", change("-0.20", "percentage_points", "vs 2024"))],
      chart(annual, "percent_yoy", [0, 10], ["0", "2", "4", "6", "8", "10"], [
        plot("gdp_growth_india", "India", "bar", cyan, ["8.1", "6.2", "8.4", "6.8", "7.1"]),
        plot("gdp_growth_world", "World", "bar", orange, ["6.1", "4.2", "3.8", "3.6", "3.4"]),
      ]), "Sample annual periods · 2021–2025"),
    debt_to_gdp: panel([summary("India", "74.2", "percent_of_gdp", change("1.70", "percentage_points", "vs 2024")),
      summary("US ratio (sample)", "98.4", "percent_of_gdp", change("-0.90", "percentage_points", "vs 2024"))],
      chart(annual, "percent_of_gdp", [50, 100], ["50", "60", "70", "80", "90", "100"], [
        plot("debt_to_gdp_india", "India", "area", cyan, ["88.4", "76.5", "62.3", "72.5", "74.2"]),
      ]), "Sample annual periods · live comparison unresolved"),
    // Sample Sep 2025 references: exports 40, imports 60 (not the prior chart month).
    trade: panel([summary("Exports", "42", "usd_billion", change("5.00", "percent", "vs Sep 2025")),
      summary("Imports", "54", "usd_billion", change("-10.00", "percent", "vs Sep 2025"))],
      chart(monthly, "usd_billion", [-20, 60], ["-20", "0", "20", "40", "60"], [
        plot("imports", "Imports", "bar", cyan, ["50", "51", "53", "52", "54"]),
        plot("exports", "Exports", "bar", orange, ["36", "38", "40", "39", "42"]),
        plot("trade_balance", "Trade balance", "line", green, ["-14", "-13", "-13", "-13", "-12"]),
      ]), "Sample months · May–Sep 2026"),
    gst_collection: panel([summary("GST Collections", "1680000", "inr_crore", change("7.69", "percent", "vs FY2024–25")),
      summary("Monthly Average", "140000", "inr_crore", change("7.69", "percent", "vs FY2024–25"))],
      chart(fiscal, "inr_crore", [0, 1800000], ["0", "450000", "900000", "1350000", "1800000"], [
        plot("gst_total", "GST Collections", "bar", cyan, ["1200000", "1320000", "1440000", "1560000", "1680000"]),
        plot("gst_monthly_average", "Monthly Average", "line", yellow, ["100000", "110000", "120000", "130000", "140000"]),
      ]), "Sample full financial years · total and monthly mean"),
    inflation_india: panel([summary("Inflation Rate", "4.1", "percent_yoy", change("-0.60", "percentage_points", "vs Aug 2026")),
      summary("RBI Target (sample)", "4.5", "percent")],
      chart(monthly, "percent_yoy", [0, 10], ["0", "2", "4", "6", "8", "10"], [
        plot("cpi_yoy", "Inflation", "line", cyan, ["6.4", "5.8", "3.3", "4.7", "4.1"]),
      ], [{ id: "seed_policy", label: "Policy reference (sample)", value: "4.5" }]), "Sample months and policy reference"),
    // Sample same-cutoff Sep 2025 references: total 360, capital 100.
    government_expenditure: panel([summary("Total Expenditure", "400", "inr_crore", change("11.11", "percent", "vs Sep 2025 YTD")),
      summary("Capital Expenditure", "110", "inr_crore", change("10.00", "percent", "vs Sep 2025 YTD"))],
      chart(monthly, "inr_crore", [0, 450], ["0", "90", "180", "270", "360", "450"], [
        plot("expenditure_capital", "Capital Expenditure", "bar", orange, ["60", "74", "88", "95", "110"]),
        plot("expenditure_revenue", "Revenue Expenditure", "bar", blue, ["210", "222", "248", "265", "290"]),
        plot("expenditure_total", "Total Expenditure", "total", yellow, ["270", "296", "336", "360", "400"]),
      ]), "Sample fiscal year-to-date cutoffs · May–Sep 2026"),
  };
  return { phase: "ready", message: "Seed data · illustrative sample values. Not live observations.",
    snapshot: { panels, observations: {}, quoteRetention: {}, version: "seed_demo_v1", generatedAt: new Date().toISOString(), partial: false, issues: [],
      ticker: { state: "fresh", refreshing: false, cadence: "unknown", cadenceLabel: "Static seed examples · no market feed",
        items: [
          { instrumentId: "seed_sensex", label: "SENSEX", value: "81234.56", changePoints: "321.12", changePercent: "0.40" },
          { instrumentId: "seed_bank", label: "NIFTY BANK", value: "52123.45", changePoints: "-135.60", changePercent: "-0.26" },
          { instrumentId: "seed_it", label: "NIFTY IT", value: "24789.12", changePoints: "0", changePercent: "0" },
        ].map((item) => ({ ...item, state: "fresh", precision: 2, comparisonLabel: "vs sample previous close",
          sources: [sampleSource], asOf: null, detail: "Illustrative seed quote, not a market observation." })),
      },
    },
  };
}
