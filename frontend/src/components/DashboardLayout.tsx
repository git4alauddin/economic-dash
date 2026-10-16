import type { ReactNode } from "react";
import DashboardHeader from "./DashboardHeader";
import MarketTicker from "./MarketTicker";
import type { TickerPresentation } from "../ui/ticker-model";

export default function DashboardLayout({ children, apiState, announcement, preview = false, ticker, modeControl }: { children: ReactNode; apiState: string; announcement: string; preview?: boolean; ticker?: TickerPresentation; modeControl?: ReactNode }) {
  return <div className="dashboard-page" data-dashboard-root data-api-state={apiState} data-panels-preview={preview || undefined}>
    <a className="skip-link" href="#dashboard-main">Skip to indicators</a>
    {preview && <aside className="panel-preview-notice" data-fixture-banner><strong>SYNTHETIC DATA · PREVIEW</strong><span>Not financial observations</span></aside>}
    <DashboardHeader />
    <MarketTicker model={ticker} modeControl={modeControl} />
    <main id="dashboard-main" className="dashboard-main" tabIndex={-1} aria-labelledby="dashboard-title">
      <p className="sr-only" role={apiState === "error" ? "alert" : "status"}>{announcement}</p>
      <div className="indicator-grid">{children}</div>
    </main>
  </div>;
}
