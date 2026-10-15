import { decimalSign, formatValue, MISSING } from "../../ui/format";
import type { DecimalValue, Unit } from "../../ui/types";

interface ComparisonChangeProps {
  value: DecimalValue;
  unit: Unit;
  precision: number;
  referenceLabel: string;
}

export default function ComparisonChange({ value, unit, precision, referenceLabel }: ComparisonChangeProps) {
  const sign = decimalSign(value);
  const direction = sign === null ? "missing" : sign > 0 ? "positive" : sign < 0 ? "negative" : "zero";
  const label = sign === null ? "Comparison unavailable" : sign > 0 ? "Increase" : sign < 0 ? "Decrease" : "No change";
  const display = formatValue(value, unit, precision);
  return (
    <span className={`comparison-change comparison-${direction}`} data-direction={direction}>
      <span aria-hidden="true">{sign === null ? "" : sign > 0 ? "▲" : sign < 0 ? "▼" : "•"}</span>
      <span className="sr-only">{label}: </span>
      <span>{display === MISSING ? MISSING : `${sign === 1 ? "+" : ""}${display}`}</span>
      <span className="comparison-reference">{referenceLabel}</span>
    </span>
  );
}
