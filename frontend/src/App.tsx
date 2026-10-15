import { useEffect, useState } from "react";
import { checkApiConnection } from "./api";
import DashboardHeader from "./components/DashboardHeader";
import MarketTicker from "./components/MarketTicker";
import PanelShell from "./components/PanelShell";
import { dashboardPanels } from "./dashboard-panels";

export default function App() {
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    const controller = new AbortController();

    checkApiConnection(controller.signal)
      .then(() => {
        if (!controller.signal.aborted) setStatus("ready");
      })
      .catch(() => {
        if (!controller.signal.aborted) setStatus("error");
      });

    return () => controller.abort();
  }, []);

  const message = {
    loading: "Loading dashboard…",
    ready: "Dashboard data is not available yet.",
    error: "Unable to reach the dashboard service.",
  }[status];
  const panelMessage = {
    loading: "Loading…",
    ready: "Data unavailable",
    error: "Unable to load data",
  }[status];

  return (
    <div className="dashboard-page" data-dashboard-root data-api-state={status}>
      <a className="skip-link" href="#dashboard-main">Skip to indicators</a>
      <DashboardHeader />
      <MarketTicker />
      <main id="dashboard-main" className="dashboard-main" tabIndex={-1} aria-labelledby="dashboard-title">
        <p className="sr-only" role={status === "error" ? "alert" : "status"}>{message}</p>
        <div className="indicator-grid">
          {dashboardPanels.map((panel) => (
            <PanelShell key={panel.id} panel={panel}>
              <div className="shell-placeholder">
                <div className="shell-summary-row" aria-hidden="true">
                  {[0, 1].map((slot) => (
                    <div className="shell-summary" key={slot}>
                      <span className="shell-summary-label" />
                      <span className="shell-summary-value" />
                    </div>
                  ))}
                </div>
                <div className="panel-empty">
                  <span className="empty-mark" aria-hidden="true">—</span>
                  <p>{panelMessage}</p>
                </div>
              </div>
            </PanelShell>
          ))}
        </div>
      </main>
    </div>
  );
}
