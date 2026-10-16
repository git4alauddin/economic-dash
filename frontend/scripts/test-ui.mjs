import assert from "node:assert/strict";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";
import react from "@vitejs/plugin-react";
import { contrastRatio } from "./audit-ui.mjs";

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
  const PanelMetadata = await component("panels/PanelMetadata");
  const panels = await server.ssrLoadModule("/src/components/panels/IndicatorPanels.tsx");
  const { panelPoints, default: PanelPlot } = await server.ssrLoadModule("/src/components/panels/PanelPlots.tsx");
  const { panelFixtures } = await server.ssrLoadModule("/src/preview/panel-fixtures.ts");
  const MarketTicker = await component("MarketTicker");
  const ticker = await server.ssrLoadModule("/src/ui/ticker-model.ts");
  const { tickerFixture, tickerScenarios } = await server.ssrLoadModule("/src/preview/ticker-fixtures.ts");
  const adapter = await server.ssrLoadModule("/src/data/dashboard-adapter.ts");
  const state = await server.ssrLoadModule("/src/data/dashboard-state.ts");
  const client = await server.ssrLoadModule("/src/data/dashboard-client.ts");
  const poller = await server.ssrLoadModule("/src/data/dashboard-poller.ts");
  const { apiBaseUrl } = await server.ssrLoadModule("/src/config.ts");
  const { dashboardFixture, responseFixture } = await server.ssrLoadModule("/src/preview/dashboard-fixtures.ts");
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
  await test("compact attribution keeps full accessible names, URLs and honest mixed dates", () => {
    const sources = [
      { source_id: "world_bank_gdp", name: "World Bank World Development Indicators (data)", url: "https://api.worldbank.org/data", is_nse: false },
      { source_id: "world_bank_gdp.metadata", name: "World Bank indicator metadata", url: "https://api.worldbank.org/metadata", is_nse: false },
    ];
    const compact = render(SourceAsOf, { sources, asOf: null, compact: true });
    assert.match(compact, /Dates by series/); assert.doesNotMatch(compact, /<time/);
    for (const source of sources) {
      assert.ok(compact.includes(`aria-label="${source.name}"`)); assert.ok(compact.includes(`href="${source.url}"`));
    }
    assert.equal(compact.match(/Non-NSE/g).length, 1);
    assert.ok(compact.includes(">World Bank</a>") && compact.includes(">WB metadata</a>"));
    const full = render(SourceAsOf, { sources, asOf: { value: "2025", precision: "year", kind: "period_end" } });
    assert.equal(full.match(/Non-NSE/g).length, 2); assert.ok(full.includes(`>${sources[0].name}</a>`));
    assert.ok(full.includes("Period ending") && full.includes("2025"));
    const unknown = render(SourceAsOf, { sources: [{ ...sources[0], source_id: "another_source", name: "Another publisher" }], asOf: null, compact: true });
    assert.ok(unknown.includes(">Another publisher</a>"));
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
    assert.ok(paths[1].includes("252.000 L"));
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
  await test("all six panels default to missing observations and unknown provenance", () => {
    for (const Panel of panels.indicatorPanelComponents) {
      const html = render(Panel, {});
      assert.equal((html.match(/Value unavailable/g) ?? []).length, 2);
      assert.ok(html.includes("Source unavailable") && html.includes("Period unavailable"));
      assert.ok(!html.includes("data-plot-kind="));
    }
  });
  await test("six specialized fixture plots render their series, summaries and original icons", () => {
    const kinds = ["gdp", "debt", "trade", "gst", "inflation", "expenditure"];
    panels.indicatorPanelComponents.forEach((Panel, index) => {
      const html = render(Panel, { data: panelFixtures[index] });
      assert.ok(html.includes(`data-plot-kind="${kinds[index]}"`));
      assert.ok(html.includes("Synthetic examples") && html.includes("Non-NSE"));
      assert.equal((html.match(/class="panel-icon /g) ?? []).length, 2);
      assert.ok(!/NaN|Infinity/.test(html));
    });
  });
  await test("banded bars reserve category space and negative/zero bars stay valid", () => {
    const scale = geometry.createPlotScale(5, [-10, 10], 56, true);
    assert.ok(scale.x(0) > scale.left && scale.x(4) < geometry.plotBox.right);
    const negative = geometry.barGeometry(scale, 0, -5, 0, 2);
    const positive = geometry.barGeometry(scale, 0, 5, 1, 2);
    const zero = geometry.barGeometry(scale, 1, 0);
    assert.ok(negative.height > 0 && positive.height > 0 && negative.x < positive.x);
    assert.equal(negative.y, scale.y(0));
    assert.equal(zero.height, 1);
    assert.equal(geometry.barGeometry(scale, 1, Infinity), null);
  });
  await test("area fills split at nulls and never fill across a missing period", () => {
    const scale = geometry.createPlotScale(5, [0, 10]);
    assert.equal(geometry.buildAreaPaths(["1", "2", null, "3", "4"], scale, 0).length, 2);
    assert.deepEqual(geometry.buildAreaPaths(["1", null, "2", null, "3"], scale, 0), []);
  });
  await test("expenditure stacking affects geometry, not segment or supplied total values", () => {
    const chart = panelFixtures[5].chart;
    const points = panelPoints("expenditure", chart);
    const revenue = points.find((point) => point.id === "expenditure_revenue:0");
    assert.equal(revenue.value, "210");
    assert.equal(revenue.baseValue, 60);
    assert.equal(revenue.plotValue, 270);
    const missing = { ...chart, series: chart.series.map((series) => series.id === "expenditure_capital" ? { ...series, values: [null, ...series.values.slice(1)] } : series) };
    assert.ok(panelPoints("expenditure", missing).filter((point) => point.index === 0).every((point) => point.plotValue === null));
    const changed = { ...chart, series: chart.series.map((series) => series.kind === "total" ? { ...series, values: ["271", ...series.values.slice(1)] } : series) };
    assert.equal(panelPoints("expenditure", changed).find((point) => point.id === "expenditure_total:0").value, "271");
  });
  await test("inflation reference uses the supplied value and malformed histories remain unavailable", () => {
    const chart = { ...panelFixtures[4].chart, references: [{ id: "test", label: "Synthetic reference", value: "2.25" }] };
    assert.ok(render(PanelPlot, { kind: "inflation", chart, state: "fresh" }).includes("Synthetic reference: 2.25%"));
    assert.ok(!render(PanelPlot, { kind: "inflation", chart: null, state: "unavailable" }).includes("chart-reference"));
    const bad = { ...chart, labels: ["Only one period"] };
    assert.ok(render(PanelPlot, { kind: "inflation", chart: bad, state: "fresh" }).includes("Data unavailable"));
  });
  await test("ticker defaults expose missing quotes without claiming live prices", () => {
    const html = render(MarketTicker, {});
    assert.ok(html.includes("NO DATA") && !html.includes("LIVE"));
    assert.equal((html.match(/Quote unavailable/g) ?? []).length, 3);
    assert.ok(!html.includes("81234") && html.includes('aria-expanded="false"'));
  });
  await test("ticker preserves supplied positive/negative/zero quotes and changes", () => {
    const html = render(MarketTicker, { model: tickerFixture });
    assert.ok(html.includes("81,234.56") && html.includes("52,123.45") && html.includes("0.00 index points"));
    assert.ok(html.includes("Increase: 0.40%") && html.includes("Decrease: -0.26%") && html.includes("No change: 0.00%"));
    assert.ok(html.includes("SCHEDULED") && !html.includes("LIVE"));
  });
  await test("ticker states suppress hidden values and require explicit retention", () => {
    for (const state of ["loading", "error", "empty", "unavailable"]) {
      const model = { ...tickerFixture, state };
      const html = render(MarketTicker, { model });
      assert.ok(!html.includes("81,234.56") && !html.includes("Increase: 0.40%"));
      assert.equal(ticker.quoteIsVisible(model, model.items[0]), false);
    }
    const stale = render(MarketTicker, { model: tickerScenarios.stale });
    assert.ok(stale.includes("STALE") && stale.includes("81,234.56"));
    assert.equal((stale.match(/class="ticker-stale"/g) ?? []).length, 3);
    const partial = render(MarketTicker, { model: tickerScenarios.partial });
    assert.ok(partial.includes("81,234.56") && !partial.includes("52,123.45"));
  });
  await test("ticker badge reflects actual availability before cadence or refresh", () => {
    for (const [scenario, status] of [["scheduled", "SCHEDULED"], ["delayed", "DELAYED"], ["updating", "UPDATING"], ["stale", "STALE"], ["loading", "LOADING"], ["error", "ERROR"], ["empty", "NO DATA"], ["unavailable", "NO DATA"]]) assert.equal(ticker.tickerStatus(tickerScenarios[scenario]), status);
    assert.equal(ticker.tickerStatus({ ...tickerScenarios.stale, refreshing: true }), "STALE");
    const missing = { ...tickerFixture, refreshing: true, items: tickerFixture.items.map((quote) => ({ ...quote, value: null })) };
    assert.equal(ticker.tickerStatus(missing), "NO DATA");
    assert.ok(render(MarketTicker, { model: tickerScenarios.empty }).includes("No instruments available"));
  });
  await test("adapter maps six canonical panels and preserves units/decimals and missing comparators", () => {
    const raw = dashboardFixture(), snapshot = adapter.adaptDashboard(raw);
    assert.equal(Object.keys(snapshot.panels).length, 6);
    assert.equal(snapshot.panels.gdp_growth.summaries[0].value, "7.1");
    assert.equal(snapshot.panels.gst_collection.summaries[0].unit, "inr_crore");
    assert.ok(render(panels.GstPanel, { data: snapshot.panels.gst_collection }).includes("(₹ crore)"));
    assert.equal(snapshot.panels.debt_to_gdp.summaries[1].value, null);
    assert.equal(snapshot.panels.inflation_india.chart.references[0].value, "4.5");
    assert.equal(snapshot.ticker.items[0].changePoints, "0");
    assert.equal(snapshot.panels.gdp_growth.asOf.precision, "year");
    assert.equal(snapshot.generatedAt, raw.meta.generated_at);
  });
  await test("adapter rejects malformed envelopes and timestamps with safe errors", () => {
    for (const raw of [null, [], { data: {} }, { ...dashboardFixture(), meta: { api_version: "v2" } }]) assert.throws(() => adapter.adaptDashboard(raw), /could not be validated/);
    const raw = dashboardFixture(); raw.meta.generated_at = "2025-02-30T00:00:00Z";
    assert.throws(() => adapter.adaptDashboard(raw));
  });
  await test("invalid independent series are quarantined while valid neighbors remain", () => {
    for (const change of [(series) => { series.latest.value = 7; }, (series) => { series.latest.value = "NaN"; }, (series) => { series.latest.unit = "percent"; }, (series) => { series.latest.sources = []; }, (series) => { series.latest.as_of_precision = "day"; }, (series) => { series.latest.status = ["fresh"]; }, (series) => { series.latest.observation_period.basis = ["calendar"]; }, (series) => { series.latest.as_of_kind = ["observation"]; }]) {
      const raw = dashboardFixture(); change(raw.data.panels.gdp_growth.series.gdp_growth_world);
      const snapshot = adapter.adaptDashboard(raw);
      assert.equal(snapshot.panels.gdp_growth.summaries[0].value, "7.1");
      assert.equal(snapshot.panels.gdp_growth.summaries[1].value, null);
      assert.equal(snapshot.partial, true);
    }
  });
  await test("invalid histories and comparisons do not replace valid latest observations", () => {
    const raw = dashboardFixture(), series = raw.data.panels.gdp_growth.series.gdp_growth_india;
    series.history.points[0].value = "Infinity";
    series.comparison = { value: "1", unit: "percent", precision: 2, reference_label: "unverified rate delta" };
    const snapshot = adapter.adaptDashboard(raw);
    assert.equal(snapshot.panels.gdp_growth.summaries[0].value, "7.1");
    assert.equal(snapshot.panels.gdp_growth.summaries[0].comparison, undefined);
    assert.equal(snapshot.observations.gdp_growth.gdp_growth_india.history.status, "error");
    assert.deepEqual(snapshot.panels.gdp_growth.chart.series[0].values, [null, null, null, null, null]);
    assert.equal(snapshot.panels.gdp_growth.chart.series[1].values[0], "6.1");
  });
  await test("canonical period alignment preserves gaps and does not zip mismatched histories", () => {
    const raw = dashboardFixture(), history = raw.data.panels.gdp_growth.series.gdp_growth_india.history;
    history.points.reverse();
    const missing = history.points.find((point) => point.observation_period.id === "2023");
    missing.value = null; missing.status = "unavailable";
    const snapshot = adapter.adaptDashboard(raw);
    assert.deepEqual(snapshot.panels.gdp_growth.chart.series[0].values, ["8.1", "6.2", null, "6.8", "7.1"]);
    history.points[0].observation_period.basis = "fiscal";
    assert.equal(adapter.adaptDashboard(raw).panels.gdp_growth.chart.series[0].values[4], null);
  });
  await test("aggregate date stays unknown when series dates differ and details retain original provenance", () => {
    const raw = dashboardFixture(); raw.data.panels.gdp_growth.series.gdp_growth_world.latest.as_of = "2024";
    const panel = adapter.adaptDashboard(raw).panels.gdp_growth;
    assert.equal(panel.asOf, null);
    assert.equal(panel.seriesDetails[1].asOf.value, "2024");
    assert.ok(render(panels.GdpPanel, { data: panel }).includes("Series details"));
    assert.ok(!render(panels.GdpPanel, { data: panel }).includes("2025-01-01"));
  });
  await test("only verified comparisons with explicit reference identity use supplied precision", () => {
    const raw = dashboardFixture(), series = raw.data.panels.gdp_growth.series.gdp_growth_india;
    series.precision = 3;
    series.latest.value = "9007199254740993.125";
    series.comparison = { value: "0.005", unit: "percentage_points", precision: 3, reference_label: "vs synthetic 2024", kind: "previous_year", reference_series_id: "gdp_growth_india", reference_period_id: "2024", verified: true };
    const snapshot = adapter.adaptDashboard(raw);
    assert.equal(snapshot.panels.gdp_growth.summaries[0].value, "9007199254740993.125");
    assert.equal(snapshot.panels.gdp_growth.summaries[0].comparison.value, "0.005");
    assert.equal(snapshot.panels.gdp_growth.summaries[0].precision, 3);
    series.comparison.verified = false;
    assert.equal(adapter.adaptDashboard(raw).panels.gdp_growth.summaries[0].comparison, undefined);
  });
  await test("unsafe sources and unverified policy applicability never become displayed values", () => {
    const raw = dashboardFixture();
    raw.data.panels.inflation_india.series.rbi_target.policy.applicable = false;
    raw.data.panels.trade.series.imports.latest.sources[0].url = "javascript:alert(1)";
    const snapshot = adapter.adaptDashboard(raw);
    assert.deepEqual(snapshot.panels.inflation_india.chart.references, []);
    assert.equal(snapshot.panels.inflation_india.summaries[1].value, null);
    assert.equal(snapshot.panels.trade.summaries[1].value, null);
  });
  await test("empty/unavailable results show missing values without fallback fixture numbers", () => {
    for (const name of ["empty", "unavailable"]) {
      const snapshot = adapter.adaptDashboard(responseFixture(name));
      for (const panel of Object.values(snapshot.panels)) assert.ok(panel.summaries.every((summary) => summary.value === null));
      const html = render(panels.GdpPanel, { data: snapshot.panels.gdp_growth });
      assert.ok(html.includes(name === "empty" ? "No observations" : "Data unavailable"));
      assert.ok(!html.includes("7.10%"));
    }
  });
  await test("refresh retention is checked per latest value, history point and quote without mutating cache", () => {
    const raw = dashboardFixture();
    raw.data.panels.gdp_growth.series.gdp_growth_world.latest.retention_allowed = false;
    raw.data.panels.gdp_growth.series.gdp_growth_india.history.points[1].retention_allowed = false;
    raw.data.ticker.items[0].retention_allowed = false;
    const before = adapter.adaptDashboard(raw), failed = state.failDashboard(before, "network");
    assert.equal(failed.snapshot.panels.gdp_growth.summaries[0].state, "stale");
    assert.equal(failed.snapshot.panels.gdp_growth.summaries[0].value, "7.1");
    assert.equal(failed.snapshot.panels.gdp_growth.summaries[1].value, null);
    assert.equal(failed.snapshot.panels.gdp_growth.chart.series[0].values[1], null);
    assert.equal(failed.snapshot.ticker.items[0].value, null);
    assert.equal(before.panels.gdp_growth.summaries[1].value, "3.4");
    assert.equal(state.failDashboard(failed.snapshot, "network").snapshot.panels.gdp_growth.summaries[1].value, null);
    assert.equal(state.beginRefresh(before).snapshot.ticker.refreshing, true);
  });
  await test("no retention and auth failures cannot resurrect previous protected values", () => {
    const previous = adapter.adaptDashboard(dashboardFixture(false));
    const failed = state.failDashboard(previous, "invalid");
    assert.ok(Object.values(failed.snapshot.panels).every((panel) => panel.summaries.every((summary) => summary.value === null)));
    assert.equal(state.failDashboard(previous, "unauthorized").snapshot, null);
    const raw = dashboardFixture(); raw.data.ticker.status = "error";
    const masked = adapter.adaptDashboard(raw);
    assert.equal(masked.ticker.items[0].value, null);
    assert.equal(state.failDashboard(masked, "network").snapshot.ticker.items[0].value, null);
  });
  await test("client sends only the configured backend request with an in-memory bearer token", async () => {
    let calls = 0;
    const result = await client.loadDashboard(null, new AbortController().signal, "synthetic-test-token", async (url, options) => {
      calls++; assert.equal(url, `${apiBaseUrl}/api/v1/dashboard`);
      assert.equal(options.headers.Authorization, "Bearer synthetic-test-token");
      assert.equal(options.credentials, "omit"); assert.equal(options.redirect, "error"); assert.equal(options.cache, "no-store");
      return new Response(JSON.stringify(dashboardFixture()));
    });
    assert.equal(calls, 1); assert.equal(result.phase, "ready");
    assert.equal((await client.loadDashboard(null, new AbortController().signal, "", async () => { throw new Error("must not send"); })).phase, "error");
  });
  await test("client classifies HTTP/JSON failures safely and clears cached data for unauthorized reads", async () => {
    const previous = adapter.adaptDashboard(dashboardFixture());
    const failed = await client.loadDashboard(previous, new AbortController().signal, "test", async () => new Response(null, { status: 503 }));
    assert.equal(failed.snapshot.panels.gdp_growth.summaries[0].state, "stale");
    const invalid = await client.loadDashboard(null, new AbortController().signal, "test", async () => new Response("<secret-error-page>"));
    assert.equal(invalid.snapshot, null); assert.ok(!invalid.message.includes("secret"));
    for (const status of [401, 403]) assert.equal((await client.loadDashboard(previous, new AbortController().signal, "test", async () => new Response(null, { status }))).snapshot, null);
  });
  await test("canceled responses cannot overwrite state, and observation age alone does not imply stale", async () => {
    const controller = new AbortController();
    await assert.rejects(client.loadDashboard(null, controller.signal, "test", async () => { controller.abort(); return new Response(JSON.stringify(dashboardFixture())); }), { name: "AbortError" });
    const raw = dashboardFixture(); raw.meta.generated_at = "2030-01-01T00:00:00Z";
    assert.equal(adapter.adaptDashboard(raw).panels.gdp_growth.summaries[0].state, "fresh");
  });
  await test("dashboard body limits count streamed UTF-8 bytes and reject oversized headers without retrying", async () => {
    for (const advertised of [false, true]) {
      let canceled = false, calls = 0;
      const body = new ReadableStream({ start(stream) { stream.enqueue(new TextEncoder().encode('"' + '€'.repeat(700_000))); }, cancel() { canceled = true; } });
      const result = await client.loadDashboard(null, new AbortController().signal, "test", async () => {
        calls++; return new Response(body, { headers: advertised ? { "Content-Length": "2000001" } : {} });
      });
      assert.equal(result.snapshot, null);
      assert.equal(result.message, "Unable to validate the dashboard response.");
      assert.equal(calls, 1);
      assert.equal(canceled, true);
    }
  });
  await test("dashboard streaming preserves split UTF-8 and rejects malformed UTF-8 safely", async () => {
    const raw = dashboardFixture(); raw.data.panels.gdp_growth.series.gdp_growth_world.latest.sources[0].name = "Synthetic ₹ publisher";
    const bytes = new TextEncoder().encode(JSON.stringify(raw));
    let offset = 0;
    const body = new ReadableStream({ pull(stream) {
      if (offset >= bytes.length) { stream.close(); return; }
      stream.enqueue(bytes.slice(offset, offset += 7));
    } });
    const result = await client.loadDashboard(null, new AbortController().signal, "test", async () => new Response(body));
    assert.equal(result.snapshot.observations.gdp_growth.gdp_growth_world.latest.sources[0].name, "Synthetic ₹ publisher");
    const bad = await client.loadDashboard(null, new AbortController().signal, "test", async () => new Response(new Uint8Array([0xc3, 0x28])));
    assert.equal(bad.message, "Unable to validate the dashboard response.");
    assert.equal(bad.snapshot, null);
  });
  await test("fifteen-second budget interrupts a stalled body, retains permitted data and permits a full recovery", async () => {
    const originalTimeout = AbortSignal.timeout;
    let deadline, canceled = false, started, calls = 0;
    const reading = new Promise((resolve) => { started = resolve; });
    AbortSignal.timeout = (milliseconds) => { assert.equal(milliseconds, 15_000); deadline = new AbortController(); return deadline.signal; };
    try {
      const reader = client.createDashboardReader(async (_url, options) => {
        calls++;
        if (calls === 2) return new Response(new ReadableStream({ pull() { started(); }, cancel() { canceled = true; } }, { highWaterMark: 0 }));
        assert.equal(options.headers["If-None-Match"], undefined);
        return new Response(JSON.stringify(dashboardFixture()), { headers: { ETag: '"bounded"' } });
      });
      const first = await reader.read(new AbortController().signal, "test");
      const pending = reader.read(new AbortController().signal, "test");
      await reading; deadline.abort(new DOMException("Synthetic deadline", "TimeoutError"));
      const failed = await pending;
      assert.equal(canceled, true);
      assert.equal(calls, 2);
      assert.equal(failed.view.snapshot.observations.gdp_growth.gdp_growth_world.latest.value, first.view.snapshot.observations.gdp_growth.gdp_growth_world.latest.value);
      assert.equal(failed.view.snapshot.observations.gdp_growth.gdp_growth_world.latest.status, "stale");
      assert.equal((await reader.read(new AbortController().signal, "test")).view.snapshot.observations.gdp_growth.gdp_growth_world.latest.status, "fresh");
      assert.equal(calls, 3);
    } finally { AbortSignal.timeout = originalTimeout; }
  });
  await test("caller cancellation stops a stalled body without publishing a failure snapshot", async () => {
    let canceled = false, started;
    const reading = new Promise((resolve) => { started = resolve; });
    const controller = new AbortController();
    const pending = client.loadDashboard(null, controller.signal, "test", async () => new Response(new ReadableStream({
      pull() { started(); }, cancel() { canceled = true; },
    }, { highWaterMark: 0 })));
    await reading; controller.abort();
    await assert.rejects(pending, { name: "AbortError" });
    assert.equal(canceled, true);
  });
  await test("conditional reader retains a validated snapshot on 304 without rewriting its dates", async () => {
    let calls = 0;
    const reader = client.createDashboardReader(async (_url, options) => {
      if (calls++ === 0) { assert.equal(options.headers["If-None-Match"], undefined); return new Response(JSON.stringify(dashboardFixture()), { headers: { ETag: 'W/"first"' } }); }
      assert.equal(options.headers["If-None-Match"], 'W/"first"');
      return new Response(null, { status: 304, headers: { ETag: 'W/"first"' } });
    });
    const first = await reader.read(new AbortController().signal, "token");
    const second = await reader.read(new AbortController().signal, "token");
    assert.equal(second.unchanged, true);
    assert.equal(second.view.snapshot, first.view.snapshot);
    assert.equal(second.view.snapshot.generatedAt, first.view.snapshot.generatedAt);
  });
  await test("conditional reader forces full recovery after failure and clears data across auth identities", async () => {
    let calls = 0;
    const reader = client.createDashboardReader(async (_url, options) => {
      calls++;
      if (calls === 1 || calls === 3) {
        assert.equal(options.headers["If-None-Match"], undefined);
        return new Response(JSON.stringify(dashboardFixture()), { headers: { ETag: '"accepted"' } });
      }
      if (calls === 2) return new Response(null, { status: 503 });
      if (calls === 4) return new Response(null, { status: 401 });
      assert.equal(options.headers["If-None-Match"], undefined);
      return new Response(null, { status: 503 });
    });
    const signal = new AbortController().signal;
    await reader.read(signal, "first-user");
    const failed = await reader.read(signal, "first-user");
    assert.equal(failed.view.snapshot.panels.gdp_growth.summaries[0].state, "stale");
    assert.equal((await reader.read(signal, "first-user")).view.snapshot.panels.gdp_growth.summaries[0].state, "fresh");
    const unauthorized = await reader.read(signal, "first-user");
    assert.equal(unauthorized.unauthorized, true);
    assert.equal(unauthorized.view.snapshot, null);
    assert.equal((await reader.read(signal, "second-user")).view.snapshot, null);
  });
  await test("304 without a matching in-memory validator is rejected", async () => {
    const reader = client.createDashboardReader(async () => new Response(null, { status: 304, headers: { ETag: '"unknown"' } }));
    const result = await reader.read(new AbortController().signal, "token");
    assert.equal(result.unchanged, false);
    assert.equal(result.view.phase, "error");
    assert.equal(result.view.snapshot, null);
  });
  await test("repeated API failures bound diagnostic state and recover with a full validated representation", async () => {
    let failure = false;
    const reader = client.createDashboardReader(async (_url, options) => {
      if (failure) return new Response(null, { status: 503 });
      assert.equal(options.headers["If-None-Match"], undefined);
      return new Response(JSON.stringify(dashboardFixture()), { headers: { ETag: '"recovered"' } });
    });
    const signal = new AbortController().signal;
    const first = await reader.read(signal, "token"); failure = true;
    let failed;
    for (let i = 0; i < 100; i++) failed = await reader.read(signal, "token");
    assert.equal(failed.view.snapshot.issues.length, first.view.snapshot.issues.length + 1);
    assert.equal(failed.view.snapshot.panels.gdp_growth.summaries[0].state, "stale");
    failure = false;
    const recovered = await reader.read(signal, "token");
    assert.equal(recovered.view.snapshot.panels.gdp_growth.summaries[0].state, "fresh");
    assert.deepEqual(recovered.view.snapshot.issues, first.view.snapshot.issues);
  });
  await test("partial invalid API series retain permitted prior values while valid neighbors update; validators are dropped", async () => {
    const original = dashboardFixture(), invalid = dashboardFixture(), recovered = dashboardFixture();
    invalid.data.panels.gdp_growth.series.gdp_growth_world.latest.value = "NaN";
    invalid.data.panels.gdp_growth.series.gdp_growth_india.latest.value = "1.2345";
    let calls = 0;
    const reader = client.createDashboardReader(async (_url, options) => {
      if (calls === 2) assert.equal(options.headers["If-None-Match"], undefined);
      return new Response(JSON.stringify([original, invalid, recovered][calls++]), { headers: { ETag: '"one"' } });
    });
    const signal = new AbortController().signal;
    const first = await reader.read(signal, "token"), partial = await reader.read(signal, "token");
    const old = first.view.snapshot.observations.gdp_growth.gdp_growth_world.latest;
    const retained = partial.view.snapshot.observations.gdp_growth.gdp_growth_world.latest;
    assert.equal(retained.value, old.value); assert.equal(retained.status, "stale");
    assert.deepEqual(retained.sources, old.sources); assert.deepEqual(retained.as_of, old.as_of);
    assert.equal(partial.view.snapshot.panels.gdp_growth.summaries[0].value, "1.2345");
    assert.equal(partial.view.snapshot.panels.gdp_growth.summaries[0].state, "fresh");
    assert.equal((await reader.read(signal, "token")).view.snapshot.panels.gdp_growth.summaries[1].state, "fresh");
    const prohibited = adapter.adaptDashboard(dashboardFixture(false));
    assert.equal(state.acceptDashboard(invalid, prohibited).snapshot.panels.gdp_growth.summaries[1].value, null);
  });
  await test("invalid history retains only permitted history, whereas an explicit empty history stays empty", () => {
    const previous = adapter.adaptDashboard(dashboardFixture()), raw = dashboardFixture();
    raw.data.panels.gdp_growth.series.gdp_growth_world.history.points[0].value = "NaN";
    const partial = state.acceptDashboard(raw, previous).snapshot.observations.gdp_growth.gdp_growth_world;
    assert.equal(partial.latest.status, "fresh"); assert.equal(partial.history.status, "stale");
    assert.equal(partial.history.points[0].value, previous.observations.gdp_growth.gdp_growth_world.history.points[0].value);
    raw.data.panels.gdp_growth.series.gdp_growth_world.history = { status: "empty", points: [], truncated: false };
    assert.deepEqual(state.acceptDashboard(raw, previous).snapshot.observations.gdp_growth.gdp_growth_world.history.points, []);
  });
  await test("polling coalesces overlap and schedules the next check after sixty seconds", async () => {
    let calls = 0, release;
    const jobs = new Map(), views = [];
    let identifier = 0;
    const timers = { schedule(callback, delay) { assert.equal(delay, 60_000); jobs.set(++identifier, callback); return identifier; }, cancel(id) { jobs.delete(id); } };
    const control = poller.startDashboardPolling("token", (view) => views.push(view), { timers, transport: async () => {
      calls++;
      if (calls === 1) return new Promise((resolve) => { release = resolve; });
      return new Response(null, { status: 304, headers: { ETag: '"one"' } });
    } });
    const pending = control.refresh();
    assert.equal(control.refresh(), pending);
    assert.equal(calls, 1);
    release(new Response(JSON.stringify(dashboardFixture()), { headers: { ETag: '"one"' } }));
    await pending;
    assert.equal(jobs.size, 1);
    const [id, tick] = jobs.entries().next().value; jobs.delete(id); tick();
    await control.refresh();
    assert.equal(calls, 2);
    assert.equal(views.length, 2);
    assert.equal(views[1].snapshot, views[0].snapshot);
    control.stop();
    assert.equal(jobs.size, 0);
    await control.refresh();
    assert.equal(calls, 2);
  });
  await test("polling stops and clears its validator on authorization failure", async () => {
    let calls = 0;
    const views = [];
    const control = poller.startDashboardPolling("expired", (view) => views.push(view), {
      timers: { schedule() { assert.fail("Unauthorized sessions must not schedule polling"); }, cancel() {} },
      transport: async () => { calls++; return new Response(null, { status: 401 }); },
    });
    await control.refresh();
    await control.refresh();
    assert.equal(calls, 1);
    assert.equal(views[0].snapshot, null);
    assert.equal(views[0].phase, "error");
  });
  await test("stopping polling aborts a pending response without later UI updates", async () => {
    let release;
    const views = [];
    const control = poller.startDashboardPolling("token", (view) => views.push(view), {
      timers: { schedule() { assert.fail("Stopped pollers cannot schedule"); }, cancel() {} },
      transport: async () => new Promise((resolve) => { release = resolve; }),
    });
    const pending = control.refresh();
    control.stop();
    release(new Response(JSON.stringify(dashboardFixture())));
    await assert.rejects(pending, { name: "AbortError" });
    assert.deepEqual(views, []);
  });
  await test("dense histories retain every observation and table row with one chart Tab stop", () => {
    const labels=Array.from({length:500},(_,index)=>String(1500+index));
    const points=labels.flatMap((label,index)=>[{id:`a:${index}`,index,label:`A ${label}`,value:'0'},{id:`b:${index}`,index,label:`B ${label}`,value:'5'}]);
    const html=render(ChartFrame,{title:'Dense synthetic history',description:'Test',labels,points,domain:[0,10],ticks:['0','5','10'],unit:'percent',precision:2,state:'fresh'});
    assert.equal((html.match(/tabindex="0"/g)??[]).length,1);
    assert.equal((html.match(/class="chart-point"/g)??[]).length,1000);
    assert.equal((html.match(/<tr>/g)??[]).length,1001);
    assert.ok((html.match(/<text /g)??[]).length < 15);
    assert.ok(html.includes('Left/Right, Home and End') && html.includes('B 1999'));
  });
  await test("visible history tables preserve missing values, zero and precise supplied decimals", () => {
    const data=adapter.adaptDashboard(dashboardFixture()).panels.gdp_growth;
    data.seriesDetails[0].history=[{period:'Missing',value:null,unit:'percent'},{period:'Zero',value:'0',unit:'percent'},{period:'Large',value:'9007199254740993.125',unit:'percent'}];
    data.seriesDetails[0].precision=3;
    const html=render(PanelMetadata,{data});
    assert.ok(html.includes('class="series-history-table"') && html.includes('<caption>India history (%)</caption>'));
    assert.ok(html.includes('—') && html.includes('0.000%') && html.includes('9,007,199,254,740,993.125%'));
    assert.ok(html.includes('scope="col"') && html.includes('scope="row"'));
  });
  await test("annotation and plot-boundary colors pass the scoped conservative contrast check", () => {
    assert.equal(contrastRatio('#ffffff','#000000'),21);
    assert.ok(contrastRatio('#e5edf4','#081427')>=4.5);
    assert.ok(contrastRatio('#4a9cff','#145169')>=3);
    const html=render(panels.ExpenditurePanel,{data:panelFixtures[5]});
    assert.ok(html.includes('fill="#081427"') && html.includes('class="plot-bar"') && html.includes('stroke="#4a9cff"'));
  });
} finally {
  await server.close();
}
