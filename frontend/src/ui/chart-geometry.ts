import { toChartNumber } from "./format";
import type { DecimalValue } from "./types";

export const plotBox = { width: 640, height: 320, left: 56, right: 620, top: 24, bottom: 272 };
export interface PlotScale { left: number; bandWidth: number; x: (index: number) => number; y: (value: number | null) => number | null; }

export function createPlotScale(count: number, domain: readonly [number, number], left = plotBox.left, banded = false): PlotScale | null {
  const [min, max] = domain;
  if (!Number.isInteger(count) || count < 1 || !Number.isFinite(min) || !Number.isFinite(max) || max <= min || !Number.isFinite(max - min) || !Number.isFinite(left) || left < 0 || left >= plotBox.right) return null;
  return {
    left,
    bandWidth: (plotBox.right - left) / count,
    x: (index) => banded ? left + (index + 0.5) * (plotBox.right - left) / count : count === 1 ? (left + plotBox.right) / 2 : left + index * (plotBox.right - left) / (count - 1),
    y: (value) => value === null || !Number.isFinite(value) || value < min || value > max ? null : plotBox.bottom - (value - min) / (max - min) * (plotBox.bottom - plotBox.top),
  };
}

export function buildAreaPaths(values: readonly DecimalValue[], scale: PlotScale, baseline: number): string[] {
  const baseY = scale.y(baseline);
  if (baseY === null) return [];
  const areas: string[] = [];
  let coordinates: [number, number][] = [];
  const close = () => {
    if (coordinates.length > 1) {
      const first = coordinates[0];
      const last = coordinates[coordinates.length - 1];
      areas.push(`M${first[0]},${baseY} ${coordinates.map(([x, y]) => `L${x},${y}`).join(" ")} L${last[0]},${baseY} Z`);
    }
    coordinates = [];
  };
  values.forEach((value, index) => {
    const y = scale.y(toChartNumber(value));
    if (y === null) close();
    else coordinates.push([scale.x(index), y]);
  });
  close();
  return areas;
}

export function barGeometry(scale: PlotScale, index: number, value: number, slot = 0, slots = 1, baseline = 0) {
  const y = scale.y(value);
  const baseY = scale.y(baseline);
  if (y === null || baseY === null || slots < 1) return null;
  const groupWidth = Math.min(76, scale.bandWidth * 0.68);
  const width = groupWidth / slots;
  return { x: scale.x(index) - groupWidth / 2 + slot * width, y: Math.min(y, baseY), width: Math.max(1, width - 3), height: Math.max(1, Math.abs(baseY - y)) };
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
