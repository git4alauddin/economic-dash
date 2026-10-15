import assert from "node:assert/strict";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";
import react from "@vitejs/plugin-react";

// Existing Vite transforms TS/TSX; Node's runner supplies assertions and reporting.
const server = await createServer({
  root: fileURLToPath(new URL("../", import.meta.url)), configFile: false,
  cacheDir: "node_modules/.cache/ui-tests",
  plugins: [react()], server: { middlewareMode: true, hmr: false }, appType: "custom",
});
try {
  const format = await server.ssrLoadModule("/src/ui/format.ts");
  const geometry = await server.ssrLoadModule("/src/ui/chart-geometry.ts");
  const component = async (path) => (await server.ssrLoadModule(`/src/components/${path}.tsx`)).default;
  const SummaryValue = await component("ui/SummaryValue");
  const ComparisonChange = await component("ui/ComparisonChange");
  const SourceAsOf = await component("ui/SourceAsOf");
  const StateMessage = await component("ui/StateMessage");
  const PeriodLabel = await component("ui/PeriodLabel");
  const ChartFrame = await component("charts/ChartFrame");
  const render = (type, props) => renderToStaticMarkup(createElement(type, props));

  await test("decimal display preserves values above Number's safe integer range", () => {
    assert.equal(format.formatValue("9007199254740993.125", "usd_billion", 2), "US$ 9,007,199,254,740,993.13 B");
    assert.equal(format.formatDecimal("1.005", 2), "1.01");
    assert.equal(format.formatDecimal("-1.005", 2), "-1.01");
  });
  await test("null/invalid values stay missing and genuine zero remains zero", () => {
    for (const value of [null, "", "NaN", "Infinity", "3px", " 0", "1e3"]) assert.equal(format.formatValue(value, "percent", 2), "—");
    assert.equal(format.formatValue("0", "percent", 2), "0.00%");
    assert.equal(format.formatDecimal("-0.001", 2), "0.00");
    assert.throws(() => format.formatDecimal("1", -1), RangeError);
  });
  await test("units distinguish rates, percentage points and currencies", () => {
    assert.equal(format.formatValue("0.81", "percentage_points", 2), "0.81 pp");
    assert.equal(format.formatValue("123456.789", "inr_crore", 2), "₹1,23,456.79 Cr");
    assert.equal(format.unitLabel("percent_of_gdp"), "% of GDP");
    assert.equal(format.formatValue("1234.5", "index_points", 1), "1,234.5");
  });
  await test("comparison direction follows the real sign, including negative zero", () => {
    for (const [value, direction, text] of [["0.81", "positive", "+0.81 pp"], ["-0.2", "negative", "-0.20 pp"], ["-0.00", "zero", "0.00 pp"], [null, "missing", "—"]]) {
      const html = render(ComparisonChange, { value, unit: "percentage_points", precision: 2, referenceLabel: "vs reference" });
      assert.ok(html.includes(`data-direction="${direction}"`));
      assert.ok(html.includes(text));
    }
  });
  await test("dates retain year/month precision and instants render in UTC", () => {
    assert.equal(format.formatDate("2025", "year"), "2025");
    assert.equal(format.formatDate("2025-02", "month"), "Feb 2025");
    assert.equal(format.formatDate("2024-02-29", "day"), "29 Feb 2024");
    assert.equal(format.formatDate("2025-02-01T00:30:00Z", "instant"), "1 Feb 2025, 00:30:00 UTC");
    assert.equal(format.formatDate(null, "day"), "—");
  });
  await test("invalid dates and invented precision are rejected", () => {
    for (const [value, precision] of [["2025-02-29", "day"], ["2024-02-30", "day"], ["2025-13", "month"], ["2025", "day"], ["2025-01-01T25:00:00Z", "instant"], ["2025-01-01T00:00:00+05:30", "instant"]]) assert.equal(format.formatDate(value, precision), "—");
  });
  await test("source links reject executable URLs and mark non-NSE attribution", () => {
    const html = render(SourceAsOf, { sources: [{ source_id: "example", name: "<unsafe> long source", url: "javascript:alert(1)", is_nse: false }], asOf: { value: "2025", precision: "year", kind: "period_end" } });
    assert.ok(html.includes("Non-NSE") && html.includes("Period ending") && html.includes("2025"));
    assert.ok(html.includes("&lt;unsafe&gt;"));
    assert.ok(!html.includes("href=") && !html.includes("2025-01-01"));
    assert.equal(format.safeSourceUrl("https://user:password@example.com"), null);
    assert.equal(format.safeSourceUrl("https://example.com/data"), "https://example.com/data");
  });
  await test("missing provenance is explicit and period labels are not reinterpreted", () => {
    assert.match(render(SourceAsOf, { sources: [], asOf: null }), /Source unavailable/);
    assert.match(render(PeriodLabel, { label: "FY25", basis: "fiscal" }), /FY25.*Fiscal period/);
    assert.ok(!render(PeriodLabel, { label: "FY25", basis: "fiscal" }).includes("2025-"));
  });
  await test("summary and state components expose unavailable/retained states", () => {
    assert.match(render(SummaryValue, { label: "Missing", value: null, unit: "percent", precision: 2 }), /Value unavailable/);
    assert.match(render(SummaryValue, { label: "Zero", value: "0", unit: "percent", precision: 2 }), /0.00%/);
    for (const state of ["loading", "fresh", "empty", "error", "stale", "unavailable"]) assert.ok(render(StateMessage, { state }).includes(`data-state="${state}"`));
    assert.ok(render(StateMessage, { state: "stale", detail: "Original observation retained" }).includes("Original observation retained"));
  });
  await test("chart conversion rejects non-finite/underflow values without hiding zero", () => {
    assert.equal(format.toChartNumber("0"), 0);
    assert.equal(format.toChartNumber("9".repeat(400)), null);
    assert.equal(format.toChartNumber(`0.${"0".repeat(400)}1`), null);
    assert.equal(format.toChartNumber(null), null);
  });
  await test("line paths split at missing points and retain a real zero", () => {
    const scale = geometry.createPlotScale(4, [0, 10]);
    const paths = geometry.buildLinePaths(["2.5", null, "0", "7.25"], scale);
    assert.equal(paths.length, 2);
    assert.ok(!paths[0].includes(" L"));
    assert.ok(paths[1].includes("272.000 L"));
    assert.equal(geometry.createPlotScale(3, [2, 2]), null);
    assert.equal(scale.y(Infinity), null);
  });
  await test("chart reference lines, keyboard points and data alternatives render safely", () => {
    const props = { title: "Synthetic", description: "Test", labels: ["Zero", "One"], domain: [0, 10], ticks: ["0", "5", "10"], unit: "percent", precision: 0, state: "fresh", points: [{ id: "a", index: 0, label: "Zero", value: "0" }, { id: "b", index: 1, label: "One", value: "5" }], references: [{ id: "policy", label: "Policy reference", value: "4" }] };
    const html = render(ChartFrame, props);
    assert.ok(html.includes("Policy reference: 4%") && html.includes('tabindex="0"') && html.includes("<table"));
    assert.ok(!/NaN|Infinity/.test(html));
    assert.ok(render(ChartFrame, { ...props, domain: [1, 1] }).includes("Data unavailable"));
    assert.ok(render(ChartFrame, { ...props, references: [{ id: "bad", label: "Unknown target", value: null }] }).includes("Reference unavailable: Unknown target"));
    assert.ok(render(ChartFrame, { ...props, points: [...props.points, { id: "outside", index: 1, label: "Outside", value: "500" }] }).includes("outside the scale"));
    assert.ok(render(ChartFrame, { ...props, state: "empty" }).includes("No observations"));
  });
} finally {
  await server.close();
}
