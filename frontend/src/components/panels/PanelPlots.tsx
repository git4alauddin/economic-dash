import { useId } from "react";
import ChartFrame, { type InspectionPoint } from "../charts/ChartFrame";
import { barGeometry, buildAreaPaths, buildLinePaths, plotBox, type PlotScale } from "../../ui/chart-geometry";
import { formatDecimal, toChartNumber } from "../../ui/format";
import type { PanelChart } from "../../ui/panel-models";
import type { UiState } from "../../ui/types";
import StateMessage from "../ui/StateMessage";

export type PanelKind = "gdp" | "debt" | "trade" | "gst" | "inflation" | "expenditure";

export function panelPoints(kind: PanelKind, chart: PanelChart): InspectionPoint[] {
  const bars = chart.series.filter((series) => series.kind === "bar");
  const complete = chart.labels.map((_, index) => bars.every((series) => {
    const number = toChartNumber(series.values[index]);
    return number !== null && number >= 0;
  }));
  return chart.series.flatMap((series) => series.values.map((value, index) => {
    const slot = bars.findIndex((bar) => bar.id === series.id);
    const point: InspectionPoint = { id: `${series.id}:${index}`, index, label: `${series.label} · ${chart.labels[index]}`, value, color: series.color, slot, seriesId: series.id };
    if (kind === "expenditure") {
      if (!complete[index]) point.plotValue = null;
      else if (series.kind === "bar") {
        // Addition is solely for SVG coordinates. Labels/totals stay supplied decimals.
        const base = bars.slice(0, slot).reduce((sum, previous) => sum + toChartNumber(previous.values[index])!, 0);
        point.baseValue = base;
        point.plotValue = base + toChartNumber(value)!;
      }
    }
    return point;
  }));
}

function ValueAnnotation({ x, y, value, precision, pill = false, color }: { x: number; y: number; value: string | null; precision: number; pill?: boolean; color?: string }) {
  const label = formatDecimal(value, precision);
  const width = Math.max(36, label.length * 8 + 10);
  const center = Math.min(plotBox.right - width / 2, Math.max(plotBox.left + width / 2, x));
  const baseline = Math.min(plotBox.bottom - 6, Math.max(plotBox.top + 10, y));
  return <g className="plot-annotation" aria-hidden="true" pointerEvents="none" stroke="none">
    {pill && <rect x={center - width / 2} y={baseline - 15} width={width} height="21" rx="10" fill="#081427" />}
    <text x={center} y={baseline} textAnchor="middle" fill={color ?? "#e5edf4"}>{label}</text>
  </g>;
}

export default function PanelPlot({ kind, chart, state }: { kind: PanelKind; chart: PanelChart | null; state: UiState }) {
  const id = useId();
  if (!chart || chart.labels.length === 0 || chart.series.some((series) => series.values.length !== chart.labels.length)) return <StateMessage state={state === "loading" || state === "error" || state === "empty" ? state : "unavailable"} />;
  const banded = !["debt", "inflation"].includes(kind);
  if (banded && (chart.domain[0] > 0 || chart.domain[1] < 0)) return <StateMessage state="unavailable" detail="History unavailable for the supplied scale." />;
  const points = panelPoints(kind, chart);
  const bars = chart.series.filter((series) => series.kind === "bar");
  const gradientId = (seriesId: string) => `${id}-${seriesId}`;

  const rectangleFor = (point: InspectionPoint, scale: PlotScale) => {
    const value = toChartNumber(point.value);
    const top = point.plotValue === undefined ? value : point.plotValue;
    if (value === null || top === null) return null;
    return kind === "expenditure" ? barGeometry(scale, point.index, top, 0, 1, point.baseValue) : barGeometry(scale, point.index, value, point.slot, bars.length);
  };

  const backdrop = (scale: PlotScale) => <g data-plot-kind={kind}>
    <defs>
      {chart.series.map((series) => <linearGradient key={series.id} id={gradientId(series.id)} x1="0" y1="0" x2="0" y2="1">
        <stop stopColor={series.color} stopOpacity="0.95" /><stop offset="1" stopColor={series.color} stopOpacity={kind === "expenditure" ? "0.6" : "0.15"} />
      </linearGradient>)}
    </defs>
    {chart.series.filter((series) => series.kind === "area" || kind === "inflation").map((series) => <g key={`${series.id}-area`}>
      {buildAreaPaths(series.values, scale, chart.domain[0]).map((path, index) => <path key={index} d={path} fill={`url(#${gradientId(series.id)})`} opacity="0.45" />)}
    </g>)}
    {points.filter((point) => (point.slot ?? -1) >= 0).map((point) => {
      const rectangle = rectangleFor(point, scale);
      return rectangle && <rect key={point.id} className="plot-bar" {...rectangle} rx="4" fill={`url(#${gradientId(point.seriesId!)})`} stroke={point.color} strokeWidth="1" vectorEffect="non-scaling-stroke" />;
    })}
    <g pointerEvents="none" aria-hidden="true">{chart.series.filter((series) => series.kind === "line" || series.kind === "area").map((series) => <g key={series.id}>
    {buildLinePaths(series.values, scale).map((path, index) => <path key={index} className="chart-series" d={path} style={{ stroke: series.color }} />)}
    </g>)}</g>
  </g>;

  const mark = (point: InspectionPoint, scale: PlotScale) => {
    const series = chart.series.find((candidate) => candidate.id === point.seriesId)!;
    const value = toChartNumber(point.value)!;
    const y = scale.y(point.plotValue === undefined ? value : point.plotValue)!;
    const x = scale.x(point.index);
    const annotate = chart.labels.length <= 12 || point.index % Math.ceil(chart.labels.length / 8) === 0 || point.index === chart.labels.length - 1;
    if (series.kind === "bar") {
      const rectangle = rectangleFor(point, scale);
      if (!rectangle) return null;
      return <>
        <rect {...rectangle} rx="4" fill="transparent" stroke="none" />
        {annotate && <ValueAnnotation x={rectangle.x + rectangle.width / 2} y={kind === "expenditure" ? rectangle.y + Math.min(22, rectangle.height / 2 + 4) : value < 0 ? rectangle.y + rectangle.height + 17 : rectangle.y - 8} value={point.value} precision={chart.annotationPrecision} pill={kind === "expenditure"} />}
        <g className="chart-focus-ring" aria-hidden="true" fill="none" pointerEvents="none"><rect {...rectangle} rx="4" stroke="#060a1d" strokeWidth="7" /><rect {...rectangle} rx="4" stroke="#fff" strokeWidth="3" /></g>
      </>;
    }
    return <>
      <circle cx={x} cy={y} r={series.kind === "total" ? 3 : 4} fill={series.color} />
      {annotate && <ValueAnnotation x={x} y={series.kind === "total" ? y - 12 : y + (point.index % 2 ? -13 : 24)} value={point.value} precision={chart.annotationPrecision} pill={series.kind !== "total"} />}
      <g className="chart-focus-ring" aria-hidden="true" fill="none" pointerEvents="none"><circle cx={x} cy={y} r="8" stroke="#060a1d" strokeWidth="6" /><circle cx={x} cy={y} r="8" stroke="#fff" strokeWidth="2" /></g>
    </>;
  };

  return <div className={`indicator-chart indicator-chart-${kind}`}>
    <ChartFrame title={`${kind} history`} description="Values and periods are supplied by the panel model. Missing observations remain gaps. Series details provides visible history tables when available."
      labels={chart.labels} domain={chart.domain} ticks={chart.ticks} unit={chart.unit} precision={chart.precision} axisPrecision={0}
      banded={banded} viewBoxHeight={304} state={state} points={points} references={chart.references} renderPlot={backdrop} renderMark={mark} />
  </div>;
}
