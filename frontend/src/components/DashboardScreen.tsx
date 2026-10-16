import DashboardLayout from "./DashboardLayout";
import { indicatorPanelComponents } from "./panels/IndicatorPanels";
import { dashboardPanels } from "../dashboard-panels";
import { unavailableTicker } from "../ui/ticker-model";
import type { DashboardView } from "../data/dashboard-state";
import { useEffect, useState, useSyncExternalStore, type ComponentType } from "react";
import { createPanelExplorer, type IndicatorRead } from "../data/panel-explorer";
import type { PanelProps } from "./panels/IndicatorPanels";

function InteractivePanel({ Panel, panelId, read, ...props }: PanelProps & { Panel: ComponentType<PanelProps>; panelId: string; read: IndicatorRead }) {
  const [explorer] = useState(() => createPanelExplorer(panelId, read));
  const selection = useSyncExternalStore(explorer.subscribe, explorer.getSnapshot, explorer.getSnapshot);
  useEffect(() => { explorer.attach(); return () => explorer.dispose(); }, [explorer]);
  const data = selection.loading && props.data ? { ...props.data, state: "loading" as const, chartState: "loading" as const, chart: null,
    summaries: props.data.summaries.map((item) => ({ ...item, value: null, state: "loading" as const })),
    seriesDetails: props.data.seriesDetails?.map((item) => ({ ...item, state: "loading" as const, history: [] })) } : selection.data ?? props.data;
  return <Panel {...props} data={data} explorer={{ controller: explorer, snapshot: selection }} />;
}

export default function DashboardScreen({ view, preview = false, readIndicator }: { view: DashboardView; preview?: boolean; readIndicator?: IndicatorRead }) {
  const state = view.phase === "ready" ? "unavailable" : view.phase;
  return <DashboardLayout apiState={view.phase} announcement={view.message} preview={preview}
    ticker={view.snapshot?.ticker ?? { ...unavailableTicker, state }}>
    {indicatorPanelComponents.map((Panel, index) => {
      const id = dashboardPanels[index].id, props: PanelProps = { data: view.snapshot?.panels[id], state };
      return readIndicator ? <InteractivePanel key={id} Panel={Panel} panelId={id} read={readIndicator} {...props} /> : <Panel key={id} {...props} />;
    })}
  </DashboardLayout>;
}
