import { toChartNumber } from "./format";
import type { DecimalValue } from "./types";

export const plotBox = { width: 640, height: 320, left: 56, right: 620, top: 24, bottom: 272 };
export interface PlotScale { left: number; x: (index: number) => number; y: (value: number | null) => number | null; }

export function createPlotScale(count: number, domain: readonly [number, number], left = plotBox.left): PlotScale | null {
  const [min, max] = domain;
  if (!Number.isInteger(count) || count < 1 || !Number.isFinite(min) || !Number.isFinite(max) || max <= min || !Number.isFinite(max - min) || !Number.isFinite(left) || left < 0 || left >= plotBox.right) return null;
  return {
    left,
    x: (index) => count === 1 ? (left + plotBox.right) / 2 : left + index * (plotBox.right - left) / (count - 1),
    y: (value) => value === null || !Number.isFinite(value) || value < min || value > max ? null : plotBox.bottom - (value - min) / (max - min) * (plotBox.bottom - plotBox.top),
  };
}

// A missing/invalid point breaks the path. Never bridge or forward-fill the gap.
export function buildLinePaths(values: readonly DecimalValue[], scale: PlotScale): string[] {
  const paths: string[] = [];
  let segment = "";
  values.forEach((value, index) => {
    const y = scale.y(toChartNumber(value));
    if (y === null) { if (segment) paths.push(segment); segment = ""; return; }
    segment += `${segment ? " L" : "M"}${scale.x(index).toFixed(3)},${y.toFixed(3)}`;
  });
  if (segment) paths.push(segment);
  return paths;
}
