import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

// Cross-check the backend inventory and source choices against actual UI bindings.
// --online probes selected, permitted routes in memory; never writes reports/payloads.
const root = fileURLToPath(new URL("../", import.meta.url));
const read = async (relative) => readFile(new URL(relative, import.meta.url), "utf8");
const catalog = JSON.parse(await read("../../backend/app/data/indicator-requirements.json"));
assert.ok(process.argv.slice(2).every((arg) => arg === "--online"), "Use --online or no arguments.");
const sources = JSON.parse(await read("../../backend/app/data/source-catalog.json"));
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
assert.equal(catalog.source_gate.nse_assessment, "recorded_in_source_catalog");
assert.equal(catalog.source_gate.catalog, "source-catalog.json");
for (const [id, source] of Object.entries(catalog.publishers)) {
  text(source.name, `${id} publisher`);
  const url = new URL(source.url);
  assert.equal(url.protocol, "https:");
  assert.ok(!url.username && !url.password, `${id}: credentials in public URL`);
  assert.equal(source.is_nse, id === "nse", `${id}: attribution`);
}
for (const key of ["missing", "history", "comparison", "source_metadata", "dates", "freshness", "normalization", "chart"]) text(catalog.common_requirements[key], key);
assert.equal(catalog.wire_requirements.status, "M2_draft_for_M4_acceptance");

const server = await createServer({ root, configFile: false, logLevel: "error", optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false, ws: false }, appType: "custom" });
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
  verifySources(series);
  if (process.argv.includes("--online")) await probeSources();
} finally {
  await server.close();
}

function publicUrl(value) {
  const url = new URL(value);
  assert.equal(url.protocol, "https:");
  assert.ok(!url.username && !url.password, "Credentials in source URL");
}

function verifySources(series) {
  assert.equal(sources.schema_version, 1);
  assert.equal(sources.stage, "M3.2");
  assert.equal(sources.status, "assessed_with_blockers");
  assert.equal(sources.collection_implemented, false, "M3.2 does not implement collection");
  publicUrl(sources.release_index.url);
  assert.equal(sources.release_index.access, "verified_local");
  assert.equal(sources.release_index.reuse_id, "pib");
  text(sources.release_index.scope, "Release discovery scope");
  assert.ok(/^\d{4}-\d{2}-\d{2}$/.test(sources.checked_on));
  for (const reuse of Object.values(sources.reuse)) {
    publicUrl(reuse.url);
    text(reuse.status, "Reuse status");
    text(reuse.constraint, "Reuse conditions");
    assert.equal(typeof reuse.collection_allowed, "boolean");
  }
  for (const [id, source] of Object.entries(sources.sources)) {
    publicUrl(source.url);
    for (const field of ["discovery_url", "metadata_url", "corroborating_url"]) if (source[field]) publicUrl(source[field]);
    assert.ok(catalog.publishers[source.publisher_id], `${id}: publisher missing`);
    if (source.delivery_publisher_id) assert.ok(catalog.publishers[source.delivery_publisher_id], `${id}: delivery publisher missing`);
    assert.ok(sources.reuse[source.reuse_id], `${id}: reuse policy missing`);
    assert.ok(["json", "html", "pdf"].includes(source.format), `${id}: format`);
    assert.ok(["verified_local", "verified_web", "blocked_tls", "page_only"].includes(source.access), `${id}: access status`);
    text(source.limits, `${id}: limitations`);
    const historyPeriods = new Set();
    assert.ok((source.history_releases ?? []).length <= 24, `${id}: unbounded history`);
    for (const release of source.history_releases ?? []) {
      publicUrl(release.url);
      assert.equal(source.delivery_publisher_id, "pib", `${id}: unreviewed history publisher`);
      assert.equal(new URL(release.url).hostname, new URL(source.url).hostname, `${id}: history host changed`);
      assert.ok(/^\d{4}-(0[1-9]|1[0-2])$/.test(release.period) && !historyPeriods.has(release.period), `${id}: invalid/duplicate history period`);
      historyPeriods.add(release.period);
    }
    for (const gap of source.history_unavailable ?? []) {
      publicUrl(gap.url);
      text(gap.reason_code, `${id}: historical gap reason`);
      assert.ok(!historyPeriods.has(gap.period), `${id}: rejected period cannot be enabled`);
    }
  }
  const expected = [...series.keys(), ...catalog.ticker.instruments.map((item) => item.instrument_id), ...catalog.unbound_requirements.map((item) => item.id)];
  same(Object.keys(sources.requirements), expected, "Every series, quote and unbound statistic needs a source decision");
  for (const [id, decision] of Object.entries(sources.nse_assessments)) {
    assert.ok(decision.source_ids.length, `${id}: NSE assessment missing`);
    for (const sourceId of decision.source_ids) assert.equal(sources.sources[sourceId]?.publisher_id, "nse", `${id}: non-NSE assessment source`);
    assert.ok(!/pending|absent/.test(decision.result), `${id}: assessment cannot assume NSE absence`);
    text(decision.locator, `${id}: NSE location`);
    text(decision.selection_reason, `${id}: source decision reason`);
  }
  const selected = new Set();
  let blocked = 0;
  for (const [id, item] of Object.entries(sources.requirements)) {
    const source = sources.sources[item.source_id];
    assert.ok(source, `${id}: unknown source`);
    assert.ok(sources.nse_assessments[item.nse_assessment_id], `${id}: NSE-first assessment missing`);
    const requirement = series.get(id) ?? (catalog.ticker.instruments.some((quote) => quote.instrument_id === id) ? catalog.ticker : null);
    if (requirement) {
      assert.equal(item.unit, requirement.unit, `${id}: resolved unit differs from UI`);
      assert.ok(requirement.frequency_candidates.includes(item.frequency), `${id}: frequency outside requirements`);
      if (item.basis !== null) assert.ok(requirement.period_basis_candidates.includes(item.basis), `${id}: period basis outside requirements`);
      text(item.definition_id, `${id}: definition ID`);
    }
    text(item.definition, `${id}: definition`);
    for (const auxiliary of item.auxiliary_source_ids ?? []) assert.ok(sources.sources[auxiliary], `${id}: unknown auxiliary source`);
    assert.ok(["selected", "derived", "blocked"].includes(item.status), `${id}: unknown decision state`);
    if (item.status === "blocked") {
      blocked++;
      text(item.reason_code, `${id}: unavailable reason`);
      text(item.unblock, `${id}: unblock condition`);
    } else {
      assert.ok(item.basis, `${id}: unresolved period basis cannot be selected`);
      assert.equal(source.access, "verified_local", `${id}: selected source was not reached locally`);
      assert.equal(sources.reuse[source.reuse_id].collection_allowed, true, `${id}: reuse gate is unresolved`);
      selected.add(item.source_id);
      if (item.status === "selected") {
        text(item.comparison, `${id}: comparison semantics`);
        text(item.history, `${id}: history coverage`);
      }
    }
    if (item.inputs) {
      text(item.transform_id, `${id}: transform ID`);
      text(item.gate, `${id}: transform validation gate`);
      for (const input of item.inputs) {
        const parent = sources.requirements[input];
        assert.ok(parent && input !== id, `${id}: invalid transform input ${input}`);
        for (const field of ["unit", "frequency", "basis"]) assert.equal(item[field], parent[field], `${id}: mismatched input ${field}`);
        if (item.status === "derived") assert.ok(["selected", "derived"].includes(parent.status), `${id}: blocked input cannot supply a derived value`);
      }
    }
  }
  same(catalog.source_gate.selected_source_ids, [...selected], "Source gate and decisions disagree");
  console.log(`PASS source decisions: ${expected.length - blocked} selected/derived, ${blocked} explicitly unavailable; ${selected.size} selected routes`);
  console.log("Source metadata verified; durable storage, hosted access and blocked-source clearance remain open.");
}

async function probeSources() {
  // Manual verification only: one bounded GET per selected route, no retries/storage.
  const fingerprints = {
    mospi_gdp_pib: ["PROVISIONAL ESTIMATES OF ANNUAL GROSS DOMESTIC PRODUCT", "2022-23", "2025-26"],
    commerce_trade_pib: ["Merchandise", "September 2026", "US$ Billion"],
    mospi_cpi_pib: ["Combined", "2024", "September"],
    finance_accounts_pib: ["Total Expenditure", "Revenue Account", "Capital Account"],
  };
  for (const id of catalog.source_gate.selected_source_ids) {
    const source = sources.sources[id];
    assert.equal(sources.reuse[source.reuse_id].collection_allowed, true);
    const request = async (url) => {
      const signal = AbortSignal.timeout(15000);
      const response = await fetch(url, { signal, credentials: "omit", headers: { "User-Agent": "EconomicDashboard/0.1 source-verification", Accept: "application/json,text/html" } });
      assert.equal(response.status, 200, `${id}: source HTTP ${response.status}`);
      const reader = response.body.getReader();
      const chunks = [];
      let length = 0;
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          length += value.byteLength;
          assert.ok(length <= 2_000_000, `${id}: verification response too large`);
          chunks.push(value);
        }
      } finally { await reader.cancel(); }
      const body = Buffer.concat(chunks).toString("utf8");
      assert.ok(response.headers.get("content-type")?.includes(source.format === "json" ? "json" : "html"), `${id}: content type`);
      return body;
    };
    const body = await request(source.url);
    if (source.format === "json") {
      assert.equal(id, "world_bank_gdp", "Add a source-specific probe before selecting a new JSON route");
      const [meta, rows] = JSON.parse(body);
      assert.equal(meta.sourceid, "2");
      assert.ok(Array.isArray(rows) && rows.length <= 10);
      const years = new Set();
      for (const row of rows) {
        assert.equal(row.countryiso3code, "WLD");
        assert.equal(row.indicator.id, "NY.GDP.MKTP.KD.ZG");
        assert.ok(/^\d{4}$/.test(row.date) && !years.has(row.date));
        years.add(row.date);
        assert.ok(row.value === null || (typeof row.value === "number" && Number.isFinite(row.value)));
      }
      assert.ok(rows.filter((row) => row.value !== null).length >= 5, "World GDP five-period history unavailable");
      const [, metadata] = JSON.parse(await request(source.metadata_url));
      assert.equal(metadata[0].id, "NY.GDP.MKTP.KD.ZG");
      assert.equal(metadata[0].name, "GDP growth (annual %)");
      assert.match(metadata[0].sourceNote, /constant price/i);
    } else {
      assert.ok(fingerprints[id], `${id}: add a source-specific verification fingerprint`);
      const content = body.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "").replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, "").replace(/<[^>]*>/g, " ").replace(/&nbsp;|&#160;/g, " ").replace(/\s+/g, " ");
      for (const marker of fingerprints[id]) assert.ok(content.includes(marker), `${id}: expected release marker missing: ${marker}`);
    }
    console.log(`PASS live source probe: ${id} (content checked in memory; not ingested)`);
  }
}
