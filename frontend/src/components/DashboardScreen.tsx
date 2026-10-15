import DashboardLayout from "./DashboardLayout";
import { indicatorPanelComponents } from "./panels/IndicatorPanels";
import { dashboardPanels } from "../dashboard-panels";
import { unavailableTicker } from "../ui/ticker-model";
import type { DashboardView } from "../data/dashboard-state";

export default function DashboardScreen({ view, preview = false }: { view: DashboardView; preview?: boolean }) {
  const state = view.phase === "ready" ? "unavailable" : view.phase;
  return <DashboardLayout apiState={view.phase} announcement={view.message} preview={preview}
    ticker={view.snapshot?.ticker ?? { ...unavailableTicker, state }}>
    {indicatorPanelComponents.map((Panel, index) => <Panel key={dashboardPanels[index].id} data={view.snapshot?.panels[dashboardPanels[index].id]} state={state} />)}
  </DashboardLayout>;
}
