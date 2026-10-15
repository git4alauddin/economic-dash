export default function PeriodLabel({ label, basis }: { label: string | null; basis?: "fiscal" | "calendar" }) {
  return <span className="period-label">{label || "Period unavailable"}{basis && <span> · {basis === "fiscal" ? "Fiscal period" : "Calendar period"}</span>}</span>;
}
