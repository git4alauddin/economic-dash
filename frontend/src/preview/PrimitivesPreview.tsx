import ComparisonChange from "../components/ui/ComparisonChange";
import PeriodLabel from "../components/ui/PeriodLabel";
import SourceAsOf from "../components/ui/SourceAsOf";
import StateMessage from "../components/ui/StateMessage";
import SummaryValue from "../components/ui/SummaryValue";
import ChartFrame from "../components/charts/ChartFrame";
import Legend from "../components/charts/Legend";
import { buildLinePaths } from "../ui/chart-geometry";
import { formatDate } from "../ui/format";
import type { UiState } from "../ui/types";

const examples = [
  { label: "Positive example", value: "12.345", change: "0.81" },
  { label: "Negative example", value: "-2.75", change: "-0.2" },
  { label: "Real zero", value: "0", change: "0" },
  { label: "Missing observation", value: null, change: null },
];
const values = ["2.5", null, "0", "7.25"];
const labels = ["Example A", "Missing period", "Real zero", "Example D"];

export default function PrimitivesPreview() {
  return (
    <main className="ui-preview" data-ui-preview>
      <header className="preview-banner" data-fixture-banner>
        <h1>UI primitives · synthetic examples</h1>
        <p>Preview only. Synthetic data, not financial observations.</p>
        <span className="sr-only">SYNTHETIC_UI_PREVIEW_ONLY</span>
      </header>
      <section className="preview-section">
        <h2>Values and comparisons</h2>
        <div className="preview-grid">{examples.map((example) => (
          <SummaryValue key={example.label} label={example.label} value={example.value} unit="percent_yoy" precision={2}>
            <PeriodLabel label="Example FY label" basis="fiscal" />
            <ComparisonChange value={example.change} unit="percentage_points" precision={2} referenceLabel="vs synthetic reference" />
          </SummaryValue>
        ))}</div>
      </section>
      <section className="preview-section" data-long-label>
        <h2>Large values, units and long labels</h2>
        <div className="preview-grid">
          <SummaryValue label="Deliberately long synthetic summary label to verify wrapping at narrow widths" value="9007199254740993.125" unit="usd_billion" precision={2} />
          <SummaryValue label="Synthetic currency grouping" value="123456.789" unit="inr_crore" precision={2} />
        </div>
      </section>
      <section className="preview-section">
        <h2>Precision-aware dates and provenance</h2>
        <div className="preview-dates">
          <span>{formatDate("2025", "year")}</span><span>{formatDate("2025-02", "month")}</span>
          <span>{formatDate("2024-02-29", "day")}</span><span>{formatDate("2025-02-01T00:30:00Z", "instant")}</span>
        </div>
        <SourceAsOf sources={[{ source_id: "synthetic", name: "Synthetic source with a deliberately long attribution name for wrapping checks", url: "https://example.com/reference", is_nse: false }]} asOf={{ value: "2025-02", precision: "month", kind: "observation" }} />
        <SourceAsOf sources={[]} asOf={null} />
      </section>
      <section className="preview-section">
        <h2>Shared state messages</h2>
        <div className="preview-states">{(["loading", "fresh", "empty", "error", "stale", "unavailable"] as UiState[]).map((state) => (
          <StateMessage key={state} state={state} detail={state === "stale" ? "Retained example; original date remains visible." : undefined} />
        ))}</div>
      </section>
      <section className="preview-section">
        <h2>Chart foundation · synthetic points</h2>
        <Legend items={[{ id: "example", label: "Synthetic series", color: "var(--color-cyan)", kind: "line" }, { id: "reference", label: "Synthetic reference", color: "var(--color-series-yellow)", kind: "line" }]} />
        <ChartFrame title="Synthetic chart with a missing point and real zero" description="The missing period breaks the line. All figures are synthetic."
          labels={labels} domain={[0, 10]} ticks={["0", "2", "4", "6", "8", "10"]} unit="percent" precision={2} state="fresh"
          points={values.map((value, index) => ({ id: String(index), index, label: labels[index], value }))}
          references={[{ id: "example-target", label: "Synthetic reference", value: "4" }]}
          renderPlot={(scale) => buildLinePaths(values, scale).map((path, index) => <path className="chart-series" d={path} key={index} />)} />
      </section>
    </main>
  );
}
