import type { ReactNode } from "react";
import { formatValue, MISSING } from "../../ui/format";
import type { DecimalValue, Unit } from "../../ui/types";

interface SummaryValueProps {
  label: string;
  value: DecimalValue;
  unit: Unit;
  precision: number;
  children?: ReactNode;
}

export default function SummaryValue({ label, value, unit, precision, children }: SummaryValueProps) {
  const display = formatValue(value, unit, precision);
  return (
    <div className="summary-value" role="group" aria-label={label}>
      <p className="summary-label">{label}</p>
      <strong className="summary-number" aria-label={display === MISSING ? "Value unavailable" : undefined}>{display}</strong>
      {children && <div className="summary-detail">{children}</div>}
    </div>
  );
}
