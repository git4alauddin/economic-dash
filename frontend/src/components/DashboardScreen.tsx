import DashboardLayout from "./DashboardLayout";
import { indicatorPanelComponents } from "./panels/IndicatorPanels";
import { dashboardPanels } from "../dashboard-panels";
import { unavailableTicker } from "../ui/ticker-model";
import type { DashboardView } from "../data/dashboard-state";
import { useEffect, useState, useSyncExternalStore, type ComponentType } from "react";
import { createPanelExplorer, type IndicatorRead } from "../data/panel-explorer";
import type { PanelProps } from "./panels/IndicatorPanels";

function InteractivePanel({ Panel, panelId, read, refreshSequence, ...props }: PanelProps & { Panel: ComponentType<PanelProps>; panelId: string; read: IndicatorRead; refreshSequence: number }) {
  const [explorer] = useState(() => createPanelExplorer(panelId, read));
  const selection = useSyncExternalStore(explorer.subscribe, explorer.getSnapshot, explorer.getSnapshot);
  useEffect(() => { explorer.attach(); return () => explorer.dispose(); }, [explorer]);
  useEffect(() => { void explorer.refresh(); }, [explorer, refreshSequence]);
  const data = selection.loading && props.data ? { ...props.data, state: "loading" as const, chartState: "loading" as const, chart: null,
    summaries: props.data.summaries.map((item) => ({ ...item, value: null, state: "loading" as const })),
    seriesDetails: props.data.seriesDetails?.map((item) => ({ ...item, state: "loading" as const, history: [] })) } : selection.data ?? props.data;
  return <Panel {...props} data={data} explorer={{ controller: explorer, snapshot: selection }} />;
}

export default function DashboardScreen({ view, preview = false, readIndicator, refreshSequence = 0 }: { view: DashboardView; preview?: boolean; readIndicator?: IndicatorRead; refreshSequence?: number }) {
  const state = view.phase === "ready" ? "unavailable" : view.phase;
  return <DashboardLayout apiState={view.phase} announcement={view.message} preview={preview}
    ticker={view.snapshot?.ticker ?? { ...unavailableTicker, state }}>
    {indicatorPanelComponents.map((Panel, index) => {
      const id = dashboardPanels[index].id, props: PanelProps = { data: view.snapshot?.panels[id], state };
      return readIndicator ? <InteractivePanel key={id} Panel={Panel} panelId={id} read={readIndicator} refreshSequence={refreshSequence} {...props} /> : <Panel key={id} {...props} />;
    })}
  </DashboardLayout>;
}
