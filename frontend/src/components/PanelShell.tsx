import type { ReactNode } from "react";
import type { DashboardPanelDefinition } from "../dashboard-panels";

interface PanelShellProps {
  panel: DashboardPanelDefinition;
  children: ReactNode;
}

export default function PanelShell({ panel, children }: PanelShellProps) {
  const headingId = `${panel.id}-heading`;

  return (
    <section className="indicator-panel" data-panel-id={panel.id} aria-labelledby={headingId}>
      <div className="panel-heading">
        <h2 id={headingId}>
          {panel.title}{panel.accentLabel && <> <span>{panel.accentLabel}</span></>}
        </h2>
      </div>
      <div className="panel-body">{children}</div>
    </section>
  );
}
