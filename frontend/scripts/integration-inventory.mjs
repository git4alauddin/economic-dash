// Executable M6 mapping lock. Inputs come from the real backend inventory,
// source catalog and frontend bindings; no payload/report files are written.
import assert from "node:assert/strict";

export function assertIntegrationInventory({ inventory, catalog, dashboardPanels, panelBindings, pollIntervalMs, payload, snapshot }) {
  const ids = inventory.panels.map((panel) => panel.indicator_id);
  assert.deepEqual(dashboardPanels.map((panel) => panel.id), ids, "UI panel order differs from backend inventory");
  assert.deepEqual(Object.keys(panelBindings), ids, "Panel bindings differ from the inventory");
  assert.equal(pollIntervalMs, 60_000, "JWT polling contract changed");
  const requirements = new Set();
  for (const panel of inventory.panels) {
    const binding = panelBindings[panel.indicator_id];
    assert.deepEqual(binding.summaries, panel.summaries, "Summary slot order changed");
    assert.deepEqual(binding.series.map((series) => series.id), panel.series.map((series) => series.id), "Plot series order changed");
    for (const series of panel.series) {
      const ui = binding.series.find((item) => item.id === series.id);
      const definition = catalog.requirements[series.id];
      requirements.add(series.id);
      assert.ok(definition, "Series definition missing");
      assert.equal(ui.unit, definition.unit, "Normalized and displayed units differ");
      assert.equal(ui.unit, series.unit, "Inventory and displayed units differ");
      assert.equal(ui.kind, series.role === "policy_reference" ? "line" : series.role, "Plot role changed");
      if (!payload) continue;
      const raw = payload.data.panels[panel.indicator_id].series[series.id];
      const parsed = snapshot.observations[panel.indicator_id][series.id];
      assert.equal(raw.latest.definition_id, definition.definition_id, "API definition identity changed");
      assert.equal(parsed.precision, raw.precision, "Display precision changed");
      assert.equal(parsed.latest.unit, definition.unit, "Adapted unit changed");
      for (const point of [raw.latest, ...raw.history.points]) {
        assert.equal(point.definition_id, definition.definition_id, "History/latest definition drift");
        assert.equal(point.unit, definition.unit, "History/latest unit drift");
        if (point.observation_period) {
          if (definition.basis !== null) assert.equal(point.observation_period.basis, definition.basis, "Fiscal/calendar basis changed");
          assert.equal(point.observation_period.frequency, definition.frequency, "Period frequency changed");
        }
      }
      const ends = raw.history.points.map((point) => point.observation_period.end);
      assert.deepEqual(ends, [...ends].sort(), "History must remain chronological");
      for (const [index, point] of parsed.history.points.entries()) {
        const source = raw.history.points[index];
        assert.deepEqual(point.observation_period, source.observation_period && { id: source.observation_period.id, label: source.observation_period.label, basis: source.observation_period.basis }, "Period identity/label changed in the adapter");
        assert.deepEqual(point.sources, source.sources, "Historical provenance changed");
      }
      if (raw.comparison) {
        assert.equal(raw.comparison.reference_series_id, series.id, "Comparison crossed series definitions");
        assert.equal(parsed.comparison.precision, raw.comparison.precision, "Comparison precision changed");
        assert.equal(parsed.comparison.unit, raw.comparison.unit, "Comparison units changed");
        assert.equal(parsed.comparison.reference_period_id, raw.comparison.reference_period_id, "Comparison period changed");
      }
    }
  }
  for (const item of inventory.unbound_requirements) {
    requirements.add(item.id);
    assert.equal(panelBindings[item.indicator_id].summaries[item.summary_slot], null, "Undefined summary acquired a series binding");
    assert.equal(catalog.requirements[item.id].status, "blocked", "Undefined summary must remain blocked");
  }
  for (const item of inventory.ticker.instruments) requirements.add(item.instrument_id);
  assert.deepEqual([...requirements].sort(), Object.keys(catalog.requirements).sort(), "Requirement coverage changed");
  if (payload) {
    assert.deepEqual(Object.keys(payload.data.panels), ids, "API panel order changed");
    assert.equal(payload.meta.api_version, "v1");
    assert.equal(payload.meta.poll_interval_seconds, pollIntervalMs / 1000);
    assert.ok(typeof payload.meta.data_version === "string" && payload.meta.data_version.length > 0);
    assert.deepEqual(payload.data.ticker.items.map((quote) => quote.instrument_id), inventory.ticker.instruments.map((quote) => quote.instrument_id), "Ticker order changed");
    for (const panel of inventory.panels) panel.summaries.forEach((sid, slot) => {
      const rid = sid ?? inventory.unbound_requirements.find((item) => item.indicator_id === panel.indicator_id && item.summary_slot === slot).id;
      assert.equal(payload.data.panels[panel.indicator_id].summaries[slot].requirement_id, rid, "API summary requirement changed");
    });
  }
  return { panels: ids.length, series: inventory.panels.reduce((count, panel) => count + panel.series.length, 0),
    summarySlots: inventory.panels.reduce((count, panel) => count + panel.summaries.length, 0), requirements: requirements.size };
}
