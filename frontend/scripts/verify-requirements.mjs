import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

// Cross-check the backend inventory against the actual UI bindings.
// No upstream requests, payloads, screenshots or report files.
const root = fileURLToPath(new URL("../", import.meta.url));
const read = async (relative) => readFile(new URL(relative, import.meta.url), "utf8");
const catalog = JSON.parse(await read("../../backend/app/data/indicator-requirements.json"));
function same(actual, expected, label) {
  assert.equal(new Set(actual).size, actual.length, `${label}: duplicate entries`);
  assert.deepEqual([...actual].sort(), [...expected].sort(), label);
}
function candidates(item, label) {
  assert.ok(item.candidate_source_ids.length, `${label}: source candidates missing`);
  assert.equal(item.candidate_source_ids[0], "nse", `${label}: NSE must be assessed first`);
  same(item.candidate_source_ids, [...new Set(item.candidate_source_ids)], `${label}: unique candidates`);
  for (const id of item.candidate_source_ids) assert.ok(catalog.publishers[id], `${label}: unknown publisher ${id}`);
}
function periods(item, label) {
  const allowed = ["annual", "monthly", "monthly_cumulative", "policy_event", "market_session_quote"];
  assert.ok(item.frequency_candidates.length, `${label}: frequency missing`);
  for (const frequency of item.frequency_candidates) assert.ok(allowed.includes(frequency), `${label}: unknown frequency`);
  assert.ok(item.period_basis_candidates.length, `${label}: period basis missing`);
  for (const basis of item.period_basis_candidates) assert.ok(["fiscal", "calendar"].includes(basis), `${label}: unknown period basis`);
}
function text(value, label) { assert.ok(typeof value === "string" && value.trim(), `${label}: required text missing`); }

assert.equal(catalog.schema_version, 1);
assert.equal(catalog.status, "requirements_only");
assert.equal(catalog.source_gate.stage, "M3.2");
assert.equal(catalog.source_gate.nse_assessment, "pending_for_every_requirement");
assert.deepEqual(catalog.source_gate.selected_source_ids, [], "M3.1 must not approve source candidates");
for (const [id, source] of Object.entries(catalog.publishers)) {
  text(source.name, `${id} publisher`);
  const url = new URL(source.url);
  assert.equal(url.protocol, "https:");
  assert.ok(!url.username && !url.password, `${id}: credentials in public URL`);
  assert.equal(source.is_nse, id === "nse", `${id}: attribution`);
}
for (const key of ["missing", "history", "comparison", "source_metadata", "dates", "freshness", "normalization", "chart"]) text(catalog.common_requirements[key], key);
assert.equal(catalog.wire_requirements.status, "M2_draft_for_M4_acceptance");

const server = await createServer({ root, configFile: false, logLevel: "error", optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false }, appType: "custom" });
try {
  const { dashboardPanels } = await server.ssrLoadModule("/src/dashboard-panels.ts");
  const { panelBindings } = await server.ssrLoadModule("/src/data/dashboard-contract.ts");
  const { unavailableTicker } = await server.ssrLoadModule("/src/ui/ticker-model.ts");
  same(catalog.panels.map((panel) => panel.indicator_id), dashboardPanels.map((panel) => panel.id), "panel coverage");
  same(Object.keys(panelBindings), dashboardPanels.map((panel) => panel.id), "UI binding coverage");
  const series = new Map();
  const unbound = [];
  let summaryCount = 0;
  for (const panel of catalog.panels) {
    const binding = panelBindings[panel.indicator_id];
    assert.deepEqual(panel.summaries, binding.summaries, `${panel.indicator_id}: summary slots`);
    text(panel.reference_periods, `${panel.indicator_id}: reference periods`);
    assert.ok(panel.open_questions.length, `${panel.indicator_id}: unresolved definitions must remain explicit`);
    same(panel.series.map((item) => item.id), binding.series.map((item) => item.id), `${panel.indicator_id}: series coverage`);
    panel.summaries.forEach((id, slot) => {
      summaryCount++;
      if (id === null) unbound.push(`${panel.indicator_id}:${slot}`);
      else assert.ok(panel.series.some((item) => item.id === id), `${panel.indicator_id}: summary series missing`);
    });
    for (const item of panel.series) {
      const current = binding.series.find((entry) => entry.id === item.id);
      assert.ok(!series.has(item.id), `${item.id}: duplicate canonical series`);
      series.set(item.id, item);
      assert.equal(item.unit, current.unit, `${item.id}: unit differs from UI binding`);
      assert.equal(item.role === "policy_reference" ? "line" : item.role, current.kind, `${item.id}: chart role`);
      candidates(item, item.id);
      periods(item, item.id);
      for (const key of ["definition_candidate", "history_requirement", "comparison_requirement"]) text(item[key], `${item.id}: ${key}`);
      assert.ok(!("value" in item || "latest" in item || "selected_source_id" in item), `${item.id}: inventory is not observation data or source approval`);
    }
  }
  same(catalog.unbound_requirements.map((item) => `${item.indicator_id}:${item.summary_slot}`), unbound, "unbound summary coverage");
  same(catalog.unbound_requirements.map((item) => item.id), [...new Set(catalog.unbound_requirements.map((item) => item.id))], "unique pending requirements");
  for (const item of catalog.unbound_requirements) {
    assert.equal(item.status, "definition_unresolved");
    candidates(item, item.id);
    periods(item, item.id);
    text(item.requirement, item.id);
    text(item.unavailable_reason, item.id);
  }
  const visited = new Set();
  function visit(id, path = []) {
    assert.ok(!path.includes(id), `Circular transform inputs: ${[...path, id].join(" -> ")}`);
    assert.ok(series.has(id), `Unknown transform input ${id}`);
    if (visited.has(id)) return;
    const item = series.get(id);
    if (item.transform_candidate) {
      assert.ok(item.transform_candidate.inputs.length, `${id}: inputs missing`);
      text(item.transform_candidate.operation, `${id}: operation`);
      text(item.transform_candidate.gate, `${id}: transform gate`);
      for (const input of item.transform_candidate.inputs) visit(input, [...path, id]);
    }
    visited.add(id);
  }
  for (const id of series.keys()) visit(id);
  const target = series.get("rbi_target");
  assert.equal(target.role, "policy_reference");
  same(catalog.ticker.instruments.map((item) => item.instrument_id), unavailableTicker.items.map((item) => item.instrumentId), "ticker instrument coverage");
  for (const item of catalog.ticker.instruments) {
    assert.equal(item.label, unavailableTicker.items.find((quote) => quote.instrumentId === item.instrument_id).label);
    candidates(item, item.instrument_id);
    text(item.identity_candidate, item.instrument_id);
  }
  assert.equal(catalog.ticker.unit, "index_points");
  periods(catalog.ticker, "ticker");
  same(catalog.ticker.fields, [...new Set([...catalog.wire_requirements.ResponseObservation, ...catalog.wire_requirements.ResponseQuote])], "ticker quote fields including inherited metadata");
  for (const key of ["comparison_requirement", "history_requirement", "timing_requirement", "cadence_requirement"]) text(catalog.ticker[key], `ticker: ${key}`);
  console.log(`PASS requirements: ${catalog.panels.length} panels, ${series.size} series, ${summaryCount} summary slots (${unbound.length} unresolved), ${catalog.ticker.instruments.length} ticker instruments`);
  console.log("PASS UI units/roles, ticker metadata coverage, candidate attribution, period requirements and transform dependencies");
  console.log("Source verification and definition selection remain pending M3.2; no data was fetched or approved.");
} finally {
  await server.close();
}
