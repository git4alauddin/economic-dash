// Accept backend JSON on stdin and validate its actual frontend projection in memory.
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import react from "@vitejs/plugin-react";

let input = "";
for await (const chunk of process.stdin) input += chunk;
const payloads = JSON.parse(input);
const server = await createServer({ root: fileURLToPath(new URL("../", import.meta.url)), configFile: false,
  cacheDir: "node_modules/.cache/api-contract", plugins: [react()], server: { middlewareMode: true, hmr: false }, appType: "custom" });
try {
  const { adaptDashboard } = await server.ssrLoadModule("/src/data/dashboard-adapter.ts");
  for (const payload of Array.isArray(payloads) ? payloads : [payloads]) {
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
  process.stdout.write("PASS backend v1 payloads accepted by frontend adapter\n");
} finally {
  await server.close();
}
