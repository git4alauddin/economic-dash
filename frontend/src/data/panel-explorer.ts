import { adaptPanel } from "./dashboard-adapter";
import { panelBindings, type ApiSeries } from "./dashboard-contract";
import type { PanelPresentation } from "../ui/panel-models";
import { retainPanel } from "./dashboard-state";
import { DashboardReadError } from "./dashboard-client";
import * as v from "./validate";

export type IndicatorRead = (path: string, signal: AbortSignal) => Promise<unknown>;
export interface PeriodChoice { id: string; label: string; basis: "calendar" | "fiscal"; }
export interface SeriesChoice { id: string; label: string; blocked: boolean; periods: PeriodChoice[]; }
export interface ExplorerSnapshot {
  choices: SeriesChoice[] | null; catalogLoading: boolean; loading: boolean; refreshing: boolean;
  window: number; periods: Readonly<Record<string, string>>; data: PanelPresentation | null; message: string;
}
function envelope(raw: unknown) {
  const input = v.record(raw), meta = v.record(input.meta);
  if (meta.api_version !== "v1") throw new v.ContractError();
  return input.data;
}
export function catalogChoices(raw: unknown, panelId: string): SeriesChoice[] {
  const panels = v.list(envelope(raw), 6).map(v.record);
  const input = panels.filter((panel) => panel.indicator_id === panelId);
  if (input.length !== 1) throw new v.ContractError();
  const series = v.list(input[0].series, 10).map(v.record);
  return panelBindings[panelId].series.map((binding) => {
    const matches = series.filter((item) => item.series_id === binding.id);
    if (matches.length !== 1) throw new v.ContractError();
    const item = matches[0];
    if (!["selected", "derived", "blocked"].includes(String(item.status)) || item.unit !== binding.unit) throw new v.ContractError();
    const periods = v.list(item.available_periods, 24).map((raw) => {
      const period = v.record(raw);
      if (period.basis !== "calendar" && period.basis !== "fiscal") throw new v.ContractError();
      return { id: v.text(period.id), label: v.text(period.label), basis: period.basis } as PeriodChoice;
    });
    if (new Set(periods.map((period) => period.id)).size !== periods.length || item.status === "blocked" && periods.length) throw new v.ContractError();
    return { id: binding.id, label: v.text(item.name), blocked: item.status === "blocked", periods };
  });
}
function selectedSnapshot(raw: unknown, panelId: string, periods: Readonly<Record<string, string>>) {
  const input = v.record(envelope(raw));
  if (input.indicator_id !== panelId) throw new v.ContractError();
  const entries = v.record(input.series), parsed: Record<string, ApiSeries> = {};
  for (const binding of panelBindings[panelId].series) {
    const item = v.series(entries[binding.id], binding.unit);
    if (item.validationIssues?.length || periods[binding.id] && item.latest.observation_period?.id !== periods[binding.id]) throw new v.ContractError();
    if (binding.id === "rbi_target" && item.latest.value !== null && !item.policy?.applicable) throw new v.ContractError();
    parsed[binding.id] = item;
  }
  const panel = adaptPanel(panelId, input, parsed);
  if (input.chart !== null && !panel.chart) throw new v.ContractError();
  return { data: panel, observations: parsed };
}
export function selectedPanel(raw: unknown, panelId: string, periods: Readonly<Record<string, string>>): PanelPresentation {
  return selectedSnapshot(raw, panelId, periods).data;
}

// One controller per mounted panel: selections survive latest polling, never logout.
export function createPanelExplorer(panelId: string, read: IndicatorRead) {
  let state: ExplorerSnapshot = { choices: null, catalogLoading: false, loading: false, refreshing: false, window: 5, periods: {}, data: null, message: "" };
  let disposed = false, generation = 0;
  let catalogRequest: AbortController | null = null, selectionRequest: AbortController | null = null;
  let accepted: ReturnType<typeof selectedSnapshot> | null = null, pending: Promise<void> | null = null;
  const listeners = new Set<() => void>();
  const publish = (changes: Partial<ExplorerSnapshot>) => { if (!disposed) { state = { ...state, ...changes }; listeners.forEach((listener) => listener()); } };
  async function open() {
    if (disposed || state.choices || catalogRequest) return;
    const controller = new AbortController(); catalogRequest = controller;
    publish({ catalogLoading: true, message: "" });
    try { const choices = catalogChoices(await read("/indicators?window=24", controller.signal), panelId); if (!controller.signal.aborted) publish({ choices }); }
    catch { if (!controller.signal.aborted) publish({ message: "Period choices could not be loaded. Close and reopen details to retry." }); }
    finally { if (catalogRequest === controller) { catalogRequest = null; publish({ catalogLoading: false }); } }
  }
  function request(window: number, periods: Readonly<Record<string, string>>, refreshing: boolean) {
    const id = ++generation, controller = new AbortController(); selectionRequest = controller;
    publish({ window, periods: { ...periods }, loading: !refreshing, refreshing,
      ...(refreshing ? {} : { data: null }), message: refreshing ? "Refreshing selected history…" : "Loading selected history…" });
    const query = new URLSearchParams({ window: String(window) });
    for (const [series, period] of Object.entries(periods)) query.append("period", `${series}:${period}`);
    pending = (async () => {
      try {
        const next = selectedSnapshot(await read(`/indicators/${panelId}?${query}`, controller.signal), panelId, periods);
        if (id !== generation || controller.signal.aborted) return;
        accepted = next;
        publish({ data: next.data, loading: false, refreshing: false, message: "Selected history. Refreshed with dashboard updates; Latest view resets the selection." });
      } catch (error) {
        if (id !== generation || controller.signal.aborted) return;
        if (refreshing && accepted && !(error instanceof DashboardReadError && error.kind === "unauthorized")) {
          accepted = retainPanel(panelId, accepted.observations, accepted.data, error instanceof v.ContractError || error instanceof DashboardReadError && error.kind === "invalid" ? "invalid" : "network");
          publish({ data: accepted.data, loading: false, refreshing: false, message: "Selected history refresh failed. Permitted values are stale; other values are unavailable." });
        } else {
          accepted = null;
          publish({ data: null, loading: false, refreshing: false, window: 5, periods: {}, message: "Selection could not be loaded. Showing latest dashboard." });
        }
      } finally { if (id === generation) { selectionRequest = null; pending = null; } }
    })();
    return pending;
  }
  async function select(window: number, periods: Readonly<Record<string, string>>) {
    if (disposed || !state.choices || ![5, 10, 24].includes(window)) return;
    for (const [id, period] of Object.entries(periods)) {
      const choice = state.choices.find((item) => item.id === id);
      if (!choice || choice.blocked || !choice.periods.some((item) => item.id === period)) return;
    }
    selectionRequest?.abort(); selectionRequest = null; pending = null; accepted = null; generation++;
    if (window === 5 && !Object.keys(periods).length) { publish({ window, periods, data: null, loading: false, refreshing: false, message: "Showing latest dashboard; automatic updates resumed." }); return; }
    await request(window, periods, false);
  }
  return {
    getSnapshot: () => state,
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    open, select,
    refresh() {
      if (disposed) return Promise.resolve();
      if (pending) return pending;
      return accepted ? request(state.window, state.periods, true) : Promise.resolve();
    },
    attach() { disposed = false; },
    dispose() {
      disposed = true; generation++; catalogRequest?.abort(); selectionRequest?.abort();
      catalogRequest = null; selectionRequest = null; pending = null; accepted = null;
      state = { ...state, data: null, loading: false, refreshing: false, catalogLoading: false, window: 5, periods: {} };
    },
  };
}
export type PanelExplorer = ReturnType<typeof createPanelExplorer>;
