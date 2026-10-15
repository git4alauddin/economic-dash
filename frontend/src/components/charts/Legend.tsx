export interface LegendItem { id: string; label: string; color: string; kind?: "bar" | "line"; }

export default function Legend({ items }: { items: readonly LegendItem[] }) {
  return <ul className="chart-legend" aria-label="Chart legend">{items.map((item) => (
    <li key={item.id}><span className={`legend-key legend-${item.kind ?? "bar"}`} style={{ backgroundColor: item.color }} aria-hidden="true" />{item.label}</li>
  ))}</ul>;
}
