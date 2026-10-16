import type { ReactNode } from "react";
import { formatValue, MISSING } from "../../ui/format";
import type { DecimalValue, Unit } from "../../ui/types";

interface SummaryValueProps {
  label: string;
  value: DecimalValue;
  unit: Unit;
  precision: number;
  children?: ReactNode;
  comparison?: ReactNode;
  icon?: ReactNode;
  iconPlacement?: "inline" | "corner";
}

export default function SummaryValue({ label, value, unit, precision, children, comparison, icon, iconPlacement = "inline" }: SummaryValueProps) {
  const display = formatValue(value, unit, precision);
  return (
    <div className="summary-value" role="group" aria-label={label}>
      <div className="summary-label-row">{icon && iconPlacement === "inline" && <span className="summary-inline-icon" aria-hidden="true">{icon}</span>}<p className="summary-label">{label}</p></div>
      <div className="summary-metrics">
        <strong className="summary-number" data-unit={unit} aria-label={display === MISSING ? "Value unavailable" : undefined}>{display}</strong>
        {comparison && <div className="summary-comparison">{comparison}</div>}
      </div>
      {children && <div className="summary-detail">{children}</div>}
      {icon && iconPlacement === "corner" && <span className="summary-artwork" aria-hidden="true">{icon}</span>}
    </div>
  );
}
