// Accept backend JSON on stdin and validate its actual frontend projection in memory.
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import react from "@vitejs/plugin-react";

let input = "";
for await (const chunk of process.stdin) input += chunk;
const payloads = JSON.parse(input);
const transcript = !Array.isArray(payloads) && payloads.polling ? payloads.polling : null;
const server = await createServer({ root: fileURLToPath(new URL("../", import.meta.url)), configFile: false,
  cacheDir: "node_modules/.cache/api-contract", plugins: [react()], server: { middlewareMode: true, hmr: false }, appType: "custom" });
try {
  const { adaptDashboard } = await server.ssrLoadModule("/src/data/dashboard-adapter.ts");
  for (const payload of transcript ? transcript.filter((r) => r.status === 200).map((r) => r.body) : Array.isArray(payloads) ? payloads : [payloads]) {
    const snapshot = adaptDashboard(payload);
    assert.equal(Object.keys(snapshot.panels).length, 6);
    assert.equal(snapshot.ticker.items.length, 3);
    assert.ok(!snapshot.issues.some((issue) => issue.includes("invalid") || issue.includes("unavailable")), snapshot.issues.join("; "));
    assert.equal(Object.values(snapshot.observations).reduce((n, entries) => n + Object.keys(entries).length, 0), 13);
    for (const [id, entries] of Object.entries(snapshot.observations)) {
      const nonempty = Object.values(entries).some((entry) => entry.history.points.some((p) => p.value !== null));
      if (nonempty) assert.ok(snapshot.panels[id].chart, `${id}: populated chart was lost`);
      for (const entry of Object.values(entries)) assert.deepEqual(entry.validationIssues, []);
    }
  }
  if (transcript) {
    const { createDashboardReader } = await server.ssrLoadModule("/src/data/dashboard-client.ts");
    let index = 0;
    const reader = createDashboardReader(async (_url, options) => {
      const item = transcript[index++];
      assert.equal(options.headers["If-None-Match"] ?? null, item.expected_if_none_match);
      return new Response(item.status === 200 ? JSON.stringify(item.body) : null, { status: item.status, headers: item.headers });
    });
    let previous = null;
    for (const item of transcript) {
      const result = await reader.read(new AbortController().signal, "explicit-test-override");
      if (item.status === 304) { assert.equal(result.unchanged, true); assert.equal(result.view.snapshot, previous); }
      else if (item.status === 401) { assert.equal(result.unauthorized, true); assert.equal(result.view.snapshot, null); }
      else assert.equal(result.view.snapshot.observations.gdp_growth.gdp_growth_world.latest.status, item.expected_world_status);
      previous = result.view.snapshot;
    }
    process.stdout.write("PASS conditional polling: changed/unchanged, expiry, recovery and auth clearing\n");
  }
  process.stdout.write("PASS backend v1 payloads accepted by frontend adapter\n");
} finally {
  await server.close();
}
