// Accept backend JSON on stdin and validate its actual frontend projection in memory.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import react from "@vitejs/plugin-react";
import { assertIntegrationInventory } from "./integration-inventory.mjs";

let input = "";
for await (const chunk of process.stdin) input += chunk;
const payloads = JSON.parse(input);
const transcript = !Array.isArray(payloads) && payloads.polling ? payloads.polling : null;
const server = await createServer({ root: fileURLToPath(new URL("../", import.meta.url)), configFile: false,
  cacheDir: "node_modules/.cache/api-contract", plugins: [react()], server: { middlewareMode: true, hmr: false }, appType: "custom" });
try {
  const { adaptDashboard } = await server.ssrLoadModule("/src/data/dashboard-adapter.ts");
  const { panelBindings } = await server.ssrLoadModule("/src/data/dashboard-contract.ts");
  const { dashboardPanels } = await server.ssrLoadModule("/src/dashboard-panels.ts");
  const { DASHBOARD_POLL_INTERVAL_MS } = await server.ssrLoadModule("/src/data/dashboard-poller.ts");
  const catalog = JSON.parse(await readFile(new URL("../../backend/app/data/source-catalog.json", import.meta.url), "utf8"));
  const inventory = JSON.parse(await readFile(new URL("../../backend/app/data/indicator-requirements.json", import.meta.url), "utf8"));
  for (const payload of transcript ? transcript.filter((r) => r.status === 200).map((r) => r.body) : Array.isArray(payloads) ? payloads : [payloads]) {
    const snapshot = adaptDashboard(payload);
    assertIntegrationInventory({ inventory, catalog, dashboardPanels, panelBindings,
      pollIntervalMs: DASHBOARD_POLL_INTERVAL_MS, payload, snapshot });
    assert.equal(Object.keys(snapshot.panels).length, 6);
    assert.equal(snapshot.ticker.items.length, 3);
    assert.ok(!snapshot.issues.some((issue) => issue.includes("invalid") || issue.includes("unavailable")), snapshot.issues.join("; "));
    assert.equal(Object.values(snapshot.observations).reduce((n, entries) => n + Object.keys(entries).length, 0), 13);
    for (const [id, entries] of Object.entries(snapshot.observations)) {
      assert.deepEqual(Object.keys(entries).sort(), panelBindings[id].series.map((s) => s.id).sort());
      assert.equal(snapshot.panels[id].summaries.length, 2);
      const nonempty = Object.values(entries).some((entry) => entry.history.points.some((p) => p.value !== null));
      if (nonempty) assert.ok(snapshot.panels[id].chart, `${id}: populated chart was lost`);
      for (const [sid, entry] of Object.entries(entries)) {
        assert.deepEqual(entry.validationIssues, []);
        const raw = payload.data.panels[id].series[sid];
        assert.equal(entry.latest.value, raw.latest.value, `${sid}: decimal value changed`);
        assert.equal(entry.latest.status, raw.latest.status, `${sid}: status changed`);
        assert.deepEqual(entry.latest.sources, raw.latest.sources, `${sid}: attribution changed`);
        if (raw.latest.as_of !== null) assert.equal(entry.latest.as_of.value, raw.latest.as_of, `${sid}: date changed`);
        if (catalog.requirements[sid].status === "blocked") {
          assert.equal(entry.latest.value, null);
          assert.equal(entry.latest.reason_code, catalog.requirements[sid].reason_code);
        }
        assert.deepEqual(entry.history.points.map((p) => p.value), raw.history.points.map((p) => p.value), `${sid}: history changed`);
      }
      panelBindings[id].summaries.forEach((sid, slot) => {
        assert.equal(snapshot.panels[id].summaries[slot].value, sid ? entries[sid].latest.value : null);
      });
    }
    for (const quote of snapshot.ticker.items) {
      assert.equal(quote.value, null);
      assert.equal(quote.state, "unavailable");
      assert.ok(catalog.requirements[quote.instrumentId].reason_code);
    }
  }
  if (transcript) {
    const { createDashboardReader } = await server.ssrLoadModule("/src/data/dashboard-client.ts");
    const token = payloads.bearer_token ?? "explicit-test-override";
    let index = 0;
    const reader = createDashboardReader(async (_url, options) => {
      const item = transcript[index++];
      assert.ok(options.headers.Authorization === `Bearer ${token}`, "Reader lost its bearer authorization");
      assert.equal(options.headers["If-None-Match"] ?? null, item.expected_if_none_match);
      return new Response(item.status === 200 ? JSON.stringify(item.body) : null, { status: item.status, headers: item.headers });
    });
    let previous = null;
    for (const item of transcript) {
      const result = await reader.read(new AbortController().signal, token);
      if (item.status === 304) { assert.equal(result.unchanged, true); assert.equal(result.view.snapshot, previous); }
      else if (item.status === 401) { assert.equal(result.unauthorized, true); assert.equal(result.view.snapshot, null); }
      else assert.equal(result.view.snapshot.observations.gdp_growth.gdp_growth_world.latest.status, item.expected_world_status);
      previous = result.view.snapshot;
    }
    process.stdout.write("PASS conditional polling transcript and authorization clearing\n");
  }
  process.stdout.write("PASS backend v1 payloads accepted by frontend adapter\n");
} finally {
  await server.close();
}
