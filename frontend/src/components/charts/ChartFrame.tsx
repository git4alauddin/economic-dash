import { useEffect, useId, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { formatDecimal, formatValue, toChartNumber, unitLabel } from "../../ui/format";
import { createPlotScale, plotBox, type PlotScale } from "../../ui/chart-geometry";
import type { DecimalValue, UiState, Unit } from "../../ui/types";
import StateMessage from "../ui/StateMessage";

export interface InspectionPoint {
  id: string; index: number; label: string; value: DecimalValue; color?: string;
  // Optional coordinates used only for SVG stacking; displayed value stays exact.
  plotValue?: number | null;
  baseValue?: number;
  slot?: number;
  seriesId?: string;
}
interface ReferenceLine { id: string; label: string; value: DecimalValue; }
interface ChartFrameProps {
  title: string;
  description: string;
  labels: readonly string[];
  domain: readonly [number, number];
  ticks: readonly string[];
  unit: Unit;
  precision: number;
  axisPrecision?: number;
  banded?: boolean;
  viewBoxHeight?: number;
  state: UiState;
  points: readonly InspectionPoint[];
  references?: readonly ReferenceLine[];
  renderPlot?: (scale: PlotScale) => ReactNode;
  renderMark?: (point: InspectionPoint, scale: PlotScale) => ReactNode;
}

export default function ChartFrame({ title, description, labels, domain, ticks, unit, precision, axisPrecision = precision, banded = false, viewBoxHeight = plotBox.height, state, points, references = [], renderPlot, renderMark }: ChartFrameProps) {
  const id = useId();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);
  const frame = useRef<HTMLElement>(null);
  const [cssWidth, setCssWidth] = useState(plotBox.width);
  const axisFont = Math.max(16, 10 * plotBox.width / cssWidth);
  const smallFont = Math.max(13, 10 * plotBox.width / cssWidth);
  const axisValue = (value: DecimalValue) => unit === "inr_crore" || unit === "usd_billion" || unit === "index_points" ? formatDecimal(value, axisPrecision) : formatValue(value, unit, axisPrecision);
  const tickWidth = Math.max(0, ...ticks.map((tick) => axisValue(tick).length)) * axisFont * 0.66 + 12;
  const scale = createPlotScale(labels.length, domain, Math.min(240, Math.max(plotBox.left, tickWidth)), banded);
  const validPoints = scale ? points.filter((point) => Number.isInteger(point.index) && point.index >= 0 && point.index < labels.length && toChartNumber(point.value) !== null && scale.y(point.plotValue === undefined ? toChartNumber(point.value) : point.plotValue) !== null) : [];
  const active = validPoints.find((point) => point.id === activeId) ?? null;
  const tabStopId = validPoints.some((point) => point.id === focusId) ? focusId : validPoints[0]?.id;
  const labelWidth = Math.min(12, Math.max(1, ...labels.map((label) => label.length))) * axisFont * 0.56 + 12;
  const labelCapacity = Math.min(6, Math.max(2, Math.floor((plotBox.right - (scale?.left ?? plotBox.left)) / labelWidth)));
  const labelStep = Math.max(1, Math.ceil((labels.length - 1) / (labelCapacity - 1)));
  const hasPlot = Boolean(scale && validPoints.length && ["fresh", "stale"].includes(state));
  useEffect(() => {
    const node = frame.current;
    if (!node) return;
    const measure = () => setCssWidth(node.getBoundingClientRect().width || plotBox.width);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [state, hasPlot]);
  if (!["fresh", "stale"].includes(state)) return <StateMessage state={state} />;
  if (!scale || !validPoints.length) return <StateMessage state="unavailable" detail="No valid points within the supplied chart scale." />;
  const missingReferences = references.filter((reference) => scale.y(toChartNumber(reference.value)) === null);

  return (
    <figure ref={frame} className="chart-frame" data-compact-chart={cssWidth < 360 || undefined} style={{ "--chart-axis-size": `${axisFont}px`, "--chart-small-size": `${smallFont}px` } as CSSProperties}>
      {state === "stale" && <StateMessage state="stale" />}
      {(unit === "inr_crore" || unit === "usd_billion" || unit === "index_points") && <span className="chart-unit-caption" aria-hidden="true">{unitLabel(unit)}</span>}
      <svg viewBox={`0 0 ${plotBox.width} ${viewBoxHeight}`} role="group" aria-labelledby={`${id}-title`} aria-describedby={`${id}-description`}>
        <title id={`${id}-title`}>{title}</title>
        <desc id={`${id}-description`}>{description} Unit: {unitLabel(unit)}. Use Left/Right, Home and End to inspect points; Escape closes the tooltip. Tab leaves this chart. A data table follows.</desc>
        <g className="chart-axes" aria-hidden="true">
          {(unit === "inr_crore" || unit === "usd_billion" || unit === "index_points") && <text className="axis-unit" x={scale.left} y="13">{unitLabel(unit)}</text>}
          {ticks.map((tick) => {
            const y = scale.y(toChartNumber(tick));
            return y === null ? null : <g key={tick}>
              <line x1={scale.left} x2={plotBox.right} y1={y} y2={y} />
              <text x={scale.left - 8} y={y + Math.max(4, axisFont * 0.25)} textAnchor="end">{axisValue(tick)}</text>
            </g>;
          })}
          {labels.map((label, index) => index % labelStep !== 0 && index !== labels.length - 1 ? null : <text key={`${label}-${index}`} x={scale.x(index)} y={plotBox.bottom + 24} textAnchor={index === 0 ? "start" : index === labels.length - 1 ? "end" : "middle"}><title>{label}</title>{label.length > 12 ? `${label.slice(0, 11)}…` : label}</text>)}
        </g>
        {renderPlot?.(scale)}
        {references.map((reference) => {
          const y = scale.y(toChartNumber(reference.value));
          return y === null ? null : <g className="chart-reference" key={reference.id}>
            <line x1={scale.left} x2={plotBox.right} y1={y} y2={y} />
            <text x={plotBox.right} y={Math.max(plotBox.top + 14, y - 6)} textAnchor="end">{reference.label}: {formatValue(reference.value, unit, precision)}</text>
            <title>{`${reference.label}: ${formatValue(reference.value, unit, precision)}`}</title>
          </g>;
        })}
        {validPoints.map((point) => <g key={point.id} className="chart-point" fill={point.color ?? "var(--color-cyan)"}
          tabIndex={point.id === tabStopId ? 0 : -1} role="img" aria-label={`${point.label}: ${formatValue(point.value, unit, precision)}`}
          aria-describedby={active?.id === point.id ? `${id}-tooltip` : undefined}
          onPointerEnter={() => setActiveId(point.id)} onPointerLeave={(event) => { if (event.currentTarget.ownerDocument.activeElement !== event.currentTarget) setActiveId(null); }}
          onFocus={() => { setActiveId(point.id); setFocusId(point.id); }} onBlur={() => setActiveId(null)} onKeyDown={(event) => {
            if (event.key === "Escape") { setActiveId(null); return; }
            const index = validPoints.findIndex((candidate) => candidate.id === point.id);
            const destinations: Record<string, number> = { ArrowLeft: Math.max(0, index - 1), ArrowRight: Math.min(validPoints.length - 1, index + 1), Home: 0, End: validPoints.length - 1 };
            if (Object.hasOwn(destinations, event.key)) {
              event.preventDefault();
              event.currentTarget.parentElement?.querySelectorAll<SVGGElement>(".chart-point")[destinations[event.key]]?.focus();
            }
          }}>
          {renderMark ? renderMark(point, scale) : <>
            <circle cx={scale.x(point.index)} cy={scale.y(point.plotValue === undefined ? toChartNumber(point.value) : point.plotValue)!} r="5" />
            <g className="chart-focus-ring" aria-hidden="true" fill="none" pointerEvents="none"><circle cx={scale.x(point.index)} cy={scale.y(toChartNumber(point.value))!} r="9" stroke="#060a1d" strokeWidth="6" /><circle cx={scale.x(point.index)} cy={scale.y(toChartNumber(point.value))!} r="9" stroke="#fff" strokeWidth="2" /></g>
          </>}
        </g>)}
      </svg>
      {active && <div className="chart-tooltip" role="tooltip" id={`${id}-tooltip`}><strong>{active.label}</strong><span>{formatValue(active.value, unit, precision)}</span></div>}
      {points.filter((point) => point.value !== null).length > validPoints.length && <p className="chart-note">Some chart values are unavailable or outside the scale.</p>}
      {missingReferences.length > 0 && <p className="chart-note">Reference unavailable: {missingReferences.map((reference) => reference.label).join(", ")}</p>}
      <div className="sr-only"><table><caption>{title} data</caption><thead><tr><th scope="col">Period/series</th><th scope="col">Value ({unitLabel(unit)})</th></tr></thead>
        <tbody>{points.map((point) => <tr key={point.id}><th scope="row">{point.label}</th><td>{formatValue(point.value, unit, precision)}</td></tr>)}</tbody>
      </table></div>
    </figure>
  );
}
