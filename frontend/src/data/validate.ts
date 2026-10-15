import { decimalSign, formatDate, MISSING, safeSourceUrl } from "../ui/format";
import type { AsOfDate, DecimalValue, SourceReference, Unit } from "../ui/types";
import type { ApiSeries, DataStatus, Observation } from "./dashboard-contract";

export class ContractError extends Error { constructor() { super("The dashboard response could not be validated."); } }
export function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new ContractError();
  return value as Record<string, unknown>;
}
export function text(value: unknown, max = 240): string {
  if (typeof value !== "string" || !value.trim() || value.length > max) throw new ContractError();
  return value;
}
export function flag(value: unknown): boolean { if (typeof value !== "boolean") throw new ContractError(); return value; }
export function list(value: unknown, max = 500): unknown[] { if (!Array.isArray(value) || value.length > max) throw new ContractError(); return value; }
export function decimal(value: unknown): DecimalValue {
  if (value === null) return null;
  const result = text(value, 1000);
  if (decimalSign(result) === null) throw new ContractError();
  return result;
}
export function precision(value: unknown): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0 || value > 6) throw new ContractError();
  return value;
}
export function status(value: unknown): DataStatus {
  if (typeof value !== "string" || !["fresh", "stale", "empty", "error", "unavailable"].includes(value)) throw new ContractError();
  return value as DataStatus;
}
export function unit(value: unknown): Unit {
  if (typeof value !== "string" || !["percent_yoy", "percent_of_gdp", "percent", "percentage_points", "inr_crore", "usd_billion", "index_points"].includes(value)) throw new ContractError();
  return value as Unit;
}
export function asOf(raw: Record<string, unknown>): AsOfDate | null {
  if (raw.as_of === null) return null;
  const value = text(raw.as_of);
  const datePrecision = raw.as_of_precision;
  if (typeof datePrecision !== "string" || !["year", "month", "day", "instant"].includes(datePrecision) || typeof raw.as_of_kind !== "string" || !["observation", "period_end"].includes(raw.as_of_kind)) throw new ContractError();
  const result: AsOfDate = { value, precision: datePrecision as AsOfDate["precision"], kind: raw.as_of_kind as AsOfDate["kind"] };
  if (formatDate(value, result.precision) === MISSING) throw new ContractError();
  return result;
}
export function sources(value: unknown): SourceReference[] {
  const result = list(value, 20).map((item) => {
    const source = record(item), url = safeSourceUrl(text(source.url, 2000));
    if (!url) throw new ContractError();
    return { source_id: text(source.source_id), name: text(source.name), url, is_nse: flag(source.is_nse) };
  });
  if (new Set(result.map((source) => source.source_id)).size !== result.length) throw new ContractError();
  return result;
}
export function observation(value: unknown, expectedUnit: Unit): Observation {
  const raw = record(value), observationUnit = unit(raw.unit);
  if (observationUnit !== expectedUnit) throw new ContractError();
  const period = record(raw.observation_period);
  if (typeof period.basis !== "string" || !["calendar", "fiscal"].includes(period.basis)) throw new ContractError();
  const result: Observation = {
    value: decimal(raw.value), unit: observationUnit, definition_id: text(raw.definition_id),
    observation_period: { id: text(period.id), label: text(period.label), basis: period.basis as "calendar" | "fiscal" },
    as_of: asOf(raw), sources: sources(raw.sources), status: status(raw.status),
    reason_code: raw.reason_code === null ? null : text(raw.reason_code), retention_allowed: flag(raw.retention_allowed),
  };
  if (result.value !== null && (!result.sources.length || !result.as_of || !["fresh", "stale"].includes(result.status))) throw new ContractError();
  return result;
}
export function series(value: unknown, expectedUnit: Unit): ApiSeries {
  const raw = record(value), latest = observation(raw.latest, expectedUnit);
  const validationIssues: string[] = [];
  let history: ApiSeries["history"] = { status: "error", points: [], truncated: false };
  try {
    const input = record(raw.history), points = list(input.points).map((point) => observation(point, expectedUnit));
    if (new Set(points.map((point) => point.observation_period.id)).size !== points.length || points.some((point) => point.definition_id !== latest.definition_id)) throw new ContractError();
    const historyStatus = status(input.status);
    if (!["fresh", "stale"].includes(historyStatus) && points.some((point) => point.value !== null)) throw new ContractError();
    history = { status: historyStatus, points, truncated: flag(input.truncated) };
  } catch { validationIssues.push("History failed validation."); }
  let comparison: ApiSeries["comparison"] = null;
  try { if (raw.comparison !== null) {
    const item = record(raw.comparison), comparisonUnit = unit(item.unit);
    const expected = ["percent_yoy", "percent", "percent_of_gdp"].includes(expectedUnit) ? "percentage_points" : expectedUnit;
    if (comparisonUnit !== expected || item.verified !== true || typeof item.kind !== "string" || !["previous_period", "previous_year", "other_geography", "policy_reference"].includes(item.kind)) throw new ContractError();
    comparison = { value: decimal(item.value), unit: comparisonUnit, precision: precision(item.precision), reference_label: text(item.reference_label), kind: text(item.kind), reference_series_id: text(item.reference_series_id), reference_period_id: text(item.reference_period_id) };
  } } catch { validationIssues.push("Comparison failed validation."); }
  let policy: ApiSeries["policy"];
  if (raw.policy !== undefined) {
    const input = record(raw.policy), from = text(input.valid_from), to = input.valid_to === null ? null : text(input.valid_to);
    if (formatDate(from, "day") === MISSING || to !== null && (formatDate(to, "day") === MISSING || to < from)) throw new ContractError();
    policy = { applicable: flag(input.applicable), valid_from: from, valid_to: to };
  }
  return { name: text(raw.name), precision: precision(raw.precision), latest, comparison, history, policy, validationIssues };
}
