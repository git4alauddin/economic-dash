import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { createServer } from "vite";
import { assertIntegrationInventory } from "./integration-inventory.mjs";

const read = async (file) => JSON.parse(await readFile(new URL(file, import.meta.url), "utf8"));
const server = await createServer({ root: fileURLToPath(new URL("../", import.meta.url)), configFile: false,
  logLevel: "silent", server: { middlewareMode: true, hmr: false }, appType: "custom" });
try {
  const inventory = await read("../../backend/app/data/indicator-requirements.json");
  const catalog = await read("../../backend/app/data/source-catalog.json");
  const { dashboardPanels } = await server.ssrLoadModule("/src/dashboard-panels.ts");
  const { panelBindings } = await server.ssrLoadModule("/src/data/dashboard-contract.ts");
  const { DASHBOARD_POLL_INTERVAL_MS: pollIntervalMs } = await server.ssrLoadModule("/src/data/dashboard-poller.ts");
  const original = { inventory, catalog, dashboardPanels, panelBindings, pollIntervalMs };
  await test("all UI regions, roles, summary slots and normalized requirements agree", () => {
    assert.deepEqual(assertIntegrationInventory(original), { panels: 6, series: 13, summarySlots: 12, requirements: 17 });
  });
  await test("mapping lock rejects reordered panels/summaries, wrong units/roles, invented debt comparison and refresh drift", () => {
    for (const mutate of [
      (value) => value.dashboardPanels.reverse(),
      (value) => value.panelBindings.trade.summaries.reverse(),
      (value) => { value.panelBindings.trade.series[0].unit = "percent"; },
      (value) => { value.panelBindings.trade.series[0].kind = "line"; },
      (value) => { value.panelBindings.debt_to_gdp.summaries[1] = "debt_to_gdp_india"; },
      (value) => { value.pollIntervalMs = 1000; },
      (value) => { delete value.catalog.requirements.nifty_it; },
    ]) {
      const changed = structuredClone(original);
      mutate(changed);
      assert.throws(() => assertIntegrationInventory(changed));
    }
  });
} finally { await server.close(); }
