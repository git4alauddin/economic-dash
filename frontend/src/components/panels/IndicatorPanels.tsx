import { dashboardPanels } from "../../dashboard-panels";
import type { PanelPresentation, SummaryDatum } from "../../ui/panel-models";
import type { UiState, Unit } from "../../ui/types";
import PanelShell from "../PanelShell";
import SummaryValue from "../ui/SummaryValue";
import ComparisonChange from "../ui/ComparisonChange";
import PeriodLabel from "../ui/PeriodLabel";
import PanelMetadata from "./PanelMetadata";
import type { PanelExplorer, ExplorerSnapshot } from "../../data/panel-explorer";
import Legend from "../charts/Legend";
import PanelIcon, { type PanelIconKind } from "./PanelIcon";
import PanelPlot, { type PanelKind } from "./PanelPlots";

export interface PanelProps { data?: PanelPresentation; state?: UiState; explorer?: { controller: PanelExplorer; snapshot: ExplorerSnapshot }; }
interface Recipe { index: number; kind: PanelKind; labels: readonly [string, string]; units: readonly [Unit, Unit]; icons: readonly [PanelIconKind, PanelIconKind]; }
const recipes: Record<PanelKind, Recipe> = {
  gdp: { index: 0, kind: "gdp", labels: ["India", "World"], units: ["percent_yoy", "percent_yoy"], icons: ["india", "world"] },
  debt: { index: 1, kind: "debt", labels: ["India", "Ind vs US"], units: ["percent_of_gdp", "percent_of_gdp"], icons: ["india", "us"] },
  trade: { index: 2, kind: "trade", labels: ["Exports", "Imports"], units: ["usd_billion", "usd_billion"], icons: ["exports", "imports"] },
  gst: { index: 3, kind: "gst", labels: ["GST Collections", "Monthly Average"], units: ["inr_crore", "inr_crore"], icons: ["gst", "average"] },
  inflation: { index: 4, kind: "inflation", labels: ["Inflation Rate", "RBI Target"], units: ["percent_yoy", "percent"], icons: ["inflation", "target"] },
  expenditure: { index: 5, kind: "expenditure", labels: ["Total Expenditure", "Capital Expenditure"], units: ["inr_crore", "inr_crore"], icons: ["total", "capital"] },
};

function PanelContent({ recipe, data, state = "unavailable", explorer }: PanelProps & { recipe: Recipe }) {
  const summaries: readonly SummaryDatum[] = data?.summaries ?? recipe.labels.map((label, index) => ({ label, value: null, unit: recipe.units[index], precision: 2 }));
  const chart = data?.chart ?? null;
  const status = data?.state ?? state;
  const legendSeries = chart?.series.filter((series) => series.kind !== "total") ?? [];
  const legend = recipe.kind === "expenditure" ? [...legendSeries].reverse() : legendSeries;
  const panel = recipe.kind === "gst" ? { ...dashboardPanels[recipe.index], accentLabel: "(₹ crore)" } : dashboardPanels[recipe.index];
  return <PanelShell panel={panel}>
    <div className={`indicator-content content-${recipe.kind}`} data-specialized-panel={recipe.kind}>
      <div className="panel-summaries">
        {summaries.map((summary, index) => {
          const state = summary.state ?? status, available = state === "fresh" || state === "stale";
          return <SummaryValue key={index} {...summary} value={available ? summary.value : null} icon={<PanelIcon kind={recipe.icons[index]} />} iconPlacement={recipe.index < 2 ? "inline" : "corner"}>
            {available && summary.comparison && <ComparisonChange {...summary.comparison} />}
            {summary.state && state !== "fresh" && <span className={`summary-state state-${state}`}>{state === "loading" ? "Loading…" : state === "stale" ? "Stale observation" : state === "empty" ? "No observations" : state === "error" ? "Unable to load" : "Unavailable"}</span>}
            {summary.detail && <span className="summary-explanation">{summary.detail}</span>}
          </SummaryValue>;
        })}
      </div>
      <div className="panel-chart-caption"><PeriodLabel label={data?.period.label ?? null} basis={data?.period.basis} /><Legend items={legend.map((series) => ({ id: series.id, label: series.label, color: series.color, kind: series.kind === "bar" ? "bar" : "line" }))} /></div>
      <div className="panel-plot-region"><PanelPlot kind={recipe.kind} chart={chart} state={data?.chartState ?? status} /></div>
      <PanelMetadata data={data} explorer={explorer} />
    </div>
  </PanelShell>;
}

export function GdpPanel(props: PanelProps) { return <PanelContent recipe={recipes.gdp} {...props} />; }
export function DebtPanel(props: PanelProps) { return <PanelContent recipe={recipes.debt} {...props} />; }
export function TradePanel(props: PanelProps) { return <PanelContent recipe={recipes.trade} {...props} />; }
export function GstPanel(props: PanelProps) { return <PanelContent recipe={recipes.gst} {...props} />; }
export function InflationPanel(props: PanelProps) { return <PanelContent recipe={recipes.inflation} {...props} />; }
export function ExpenditurePanel(props: PanelProps) { return <PanelContent recipe={recipes.expenditure} {...props} />; }

export const indicatorPanelComponents = [GdpPanel, DebtPanel, TradePanel, GstPanel, InflationPanel, ExpenditurePanel] as const;
