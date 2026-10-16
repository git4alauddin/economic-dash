import assert from "node:assert/strict";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import react from "@vitejs/plugin-react";

const server = await createServer({ root: fileURLToPath(new URL("../", import.meta.url)), configFile: false,
  cacheDir: "node_modules/.cache/explorer-tests", plugins: [react()], server: { middlewareMode: true, hmr: false }, appType: "custom" });
try {
  const { createPanelExplorer, catalogChoices, selectedPanel } = await server.ssrLoadModule("/src/data/panel-explorer.ts");
  const { dashboardFixture } = await server.ssrLoadModule("/src/preview/dashboard-fixtures.ts");
  const { panelBindings } = await server.ssrLoadModule("/src/data/dashboard-contract.ts");
  const fixture = dashboardFixture(), id = "gdp_growth", sid = "gdp_growth_world";
  const catalog = () => ({ meta: fixture.meta, data: Object.entries(panelBindings).map(([indicator_id, binding]) => ({ indicator_id,
    series: binding.series.map((item) => ({ series_id: item.id, name: item.label, status: "selected", unit: item.unit,
      available_periods: fixture.data.panels[indicator_id].series[item.id].history.points.map((point) => point.observation_period) })) })) });
  const panel = (year = "2025") => {
    const data = structuredClone(fixture.data.panels[id]); data.indicator_id = id;
    const series = data.series[sid];
    series.latest = structuredClone(series.history.points.find((point) => point.observation_period.id === year));
    data.period_label = `Selected ${year}`;
    return { data, meta: fixture.meta };
  };
  const deferred = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };
  await test("period choices preserve API identities/bases and reject duplicate, blocked or wrong-unit periods", () => {
    const raw = catalog(), choices = catalogChoices(raw, id);
    assert.deepEqual(choices[1].periods, raw.data[0].series[1].available_periods);
    raw.data[0].series[1].available_periods.push(raw.data[0].series[1].available_periods[0]);
    assert.throws(() => catalogChoices(raw, id));
    for (const change of [{ unit: "usd_billion" }, { status: "blocked" }, { available_periods: [{ id: "x", label: "x", basis: "invented" }] }]) {
      const invalid = catalog(); Object.assign(invalid.data[0].series[1], change); assert.throws(() => catalogChoices(invalid, id));
    }
  });
  await test("selected panel validates identity, units, histories, comparisons and requested period before presentation", () => {
    const raw = panel("2024"), display = selectedPanel(raw, id, { [sid]: "2024" });
    assert.equal(display.summaries[1].value, raw.data.series[sid].latest.value);
    assert.equal(display.seriesDetails[1].asOf.value, "2024");
    assert.throws(() => selectedPanel(raw, id, { [sid]: "2023" }));
    for (const change of [{ indicator_id: "trade" }, { chart: {} }]) assert.throws(() => selectedPanel({ ...raw, data: { ...raw.data, ...change } }, id, {}));
    raw.data.series[sid].history.points[0].value = "NaN";
    assert.throws(() => selectedPanel(raw, id, {}));
  });
  await test("lazy catalog coalesces opens; only actual periods and bounded windows generate API queries", async () => {
    const calls = [], explorer = createPanelExplorer(id, async (path) => { calls.push(path); return path.startsWith("/indicators?") ? catalog() : panel("2024"); });
    assert.equal(calls.length, 0);
    await Promise.all([explorer.open(), explorer.open()]);
    assert.equal(calls.length, 1);
    await explorer.select(25, {}); await explorer.select(10, { [sid]: "2099" }); await explorer.select(10, { unknown: "2024" });
    assert.equal(calls.length, 1);
    await explorer.select(10, { [sid]: "2024" });
    const query = new URL(calls[1], "https://example.invalid");
    assert.equal(query.pathname, `/indicators/${id}`); assert.equal(query.searchParams.get("window"), "10");
    assert.deepEqual(query.searchParams.getAll("period"), [`${sid}:2024`]);
    assert.equal(explorer.getSnapshot().data.period.label, "Selected 2024");
    await explorer.select(5, {});
    assert.equal(explorer.getSnapshot().data, null); assert.deepEqual(explorer.getSnapshot().periods, {});
    assert.equal(calls.length, 2); explorer.dispose();
  });
  await test("rapid changes cancel earlier requests and late responses cannot overwrite the selected period", async () => {
    const pending = [], explorer = createPanelExplorer(id, async (path, signal) => {
      if (path.startsWith("/indicators?")) return catalog();
      const next = deferred(); pending.push({ ...next, signal }); return next.promise;
    });
    await explorer.open();
    const first = explorer.select(10, { [sid]: "2023" }), second = explorer.select(24, { [sid]: "2024" });
    assert.equal(pending[0].signal.aborted, true);
    pending[1].resolve(panel("2024")); await second; pending[0].resolve(panel("2023")); await first;
    assert.equal(explorer.getSnapshot().data.period.label, "Selected 2024");
    const third = explorer.select(10, { [sid]: "2023" }); await explorer.select(5, {});
    pending[2].resolve(panel("2023")); await third;
    assert.equal(explorer.getSnapshot().data, null); explorer.dispose();
  });
  await test("failed selections restore latest controls without relabelling previous observations", async () => {
    const explorer = createPanelExplorer(id, async (path) => { if (path.startsWith("/indicators?")) return catalog(); throw Error("private server detail"); });
    await explorer.open(); await explorer.select(10, { [sid]: "2024" });
    const state = explorer.getSnapshot();
    assert.equal(state.data, null); assert.equal(state.window, 5); assert.deepEqual(state.periods, {});
    assert.match(state.message, /Showing latest/); assert.doesNotMatch(state.message, /private/); explorer.dispose();
  });
  await test("unmount cancels lazy catalog; late completion cannot publish, including development effect replay", async () => {
    const response = deferred(); let signal;
    const explorer = createPanelExplorer(id, async (_path, requestSignal) => { signal = requestSignal; return response.promise; });
    const pending = explorer.open(); explorer.dispose(); assert.equal(signal.aborted, true);
    explorer.attach(); response.resolve(catalog()); await pending;
    assert.equal(explorer.getSnapshot().choices, null);
    await explorer.open(); assert.ok(explorer.getSnapshot().choices); explorer.dispose();
  });
} finally { await server.close(); }
