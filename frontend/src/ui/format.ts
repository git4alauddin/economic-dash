import type { DatePrecision, DecimalValue, Unit } from "./types";

export const MISSING = "—";
const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const unitLabels: Record<Unit, string> = {
  percent_yoy: "% YoY", percent_of_gdp: "% of GDP", percent: "%",
  percentage_points: "pp", inr_crore: "₹ crore", usd_billion: "US$ billion", index_points: "index points",
};

function parseDecimal(value: DecimalValue) {
  if (typeof value !== "string" || !/^[+-]?\d+(?:\.\d+)?$/.test(value)) return null;
  const [integer, fraction = ""] = value.replace(/^[+-]/, "").split(".");
  const magnitude = BigInt(integer + fraction);
  return { coefficient: value.startsWith("-") ? -magnitude : magnitude, scale: fraction.length };
}

export function decimalSign(value: DecimalValue): -1 | 0 | 1 | null {
  const parsed = parseDecimal(value);
  return parsed === null ? null : parsed.coefficient < 0n ? -1 : parsed.coefficient > 0n ? 1 : 0;
}

// Display rounding only: half away from zero, with no conversion to Number.
export function formatDecimal(value: DecimalValue, precision: number, locale = "en-US"): string {
  if (!Number.isInteger(precision) || precision < 0 || precision > 6) throw new RangeError("Display precision must be 0–6.");
  const parsed = parseDecimal(value);
  if (parsed === null) return MISSING;
  const magnitude = parsed.coefficient < 0n ? -parsed.coefficient : parsed.coefficient;
  let rounded: bigint;
  if (precision >= parsed.scale) rounded = magnitude * 10n ** BigInt(precision - parsed.scale);
  else {
    const divisor = 10n ** BigInt(parsed.scale - precision);
    rounded = magnitude / divisor + (magnitude % divisor * 2n >= divisor ? 1n : 0n);
  }
  const base = 10n ** BigInt(precision);
  const integer = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(rounded / base);
  const fraction = precision ? `.${(rounded % base).toString().padStart(precision, "0")}` : "";
  return `${parsed.coefficient < 0n && rounded !== 0n ? "-" : ""}${integer}${fraction}`;
}

export function unitLabel(unit: Unit): string { return unitLabels[unit]; }

export function formatValue(value: DecimalValue, unit: Unit, precision: number): string {
  const number = formatDecimal(value, precision, unit === "inr_crore" ? "en-IN" : "en-US");
  if (number === MISSING) return MISSING;
  switch (unit) {
    case "percent": case "percent_yoy": case "percent_of_gdp": return `${number}%`;
    case "percentage_points": return `${number} pp`;
    case "inr_crore": return `₹${number} Cr`;
    case "usd_billion": return `US$ ${number} B`;
    case "index_points": return number;
  }
}

export function formatDate(value: string | null, precision: DatePrecision): string {
  if (value === null) return MISSING;
  if (precision === "year") return /^\d{4}$/.test(value) ? value : MISSING;
  const match = /^(\d{4})-(\d{2})(?:-(\d{2}))?/.exec(value);
  if (!match) return MISSING;
  const [, year, month, day] = match;
  const monthIndex = Number(month) - 1;
  if (monthIndex < 0 || monthIndex > 11) return MISSING;
  if (precision === "month") return /^\d{4}-\d{2}$/.test(value) ? `${months[monthIndex]} ${year}` : MISSING;
  const datePart = `${year}-${month}-${day}`;
  const dayDate = new Date(`${datePart}T00:00:00Z`);
  if (!day || !Number.isFinite(dayDate.getTime()) || dayDate.toISOString().slice(0, 10) !== datePart) return MISSING;
  const displayDay = `${Number(day)} ${months[monthIndex]} ${year}`;
  if (precision === "day") return value === datePart ? displayDay : MISSING;
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/.test(value)) return MISSING;
  const instant = new Date(value);
  if (!Number.isFinite(instant.getTime()) || instant.toISOString().slice(0, 19) !== value.slice(0, 19)) return MISSING;
  return `${displayDay}, ${value.slice(11, 19)} UTC`;
}

export function safeSourceUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

// Number is permitted only at the final chart-geometry boundary.
export function toChartNumber(value: DecimalValue): number | null {
  const sign = decimalSign(value);
  if (sign === null) return null;
  const number = Number(value);
  return Number.isFinite(number) && !(sign !== 0 && number === 0) ? number : null;
}
