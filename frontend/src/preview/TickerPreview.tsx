import { useState } from "react";
import DashboardHeader from "../components/DashboardHeader";
import MarketTicker from "../components/MarketTicker";
import { tickerScenarios } from "./ticker-fixtures";

export default function TickerPreview() {
  const [scenario, setScenario] = useState("scheduled");
  return <div className="dashboard-page" data-ticker-preview>
    <a className="skip-link" href="#ticker-preview-main">Skip to preview controls</a>
    <aside className="panel-preview-notice" data-fixture-banner><strong>SYNTHETIC DATA · PREVIEW</strong><span>Not financial observations</span></aside>
    <DashboardHeader />
    <MarketTicker model={tickerScenarios[scenario]} />
    <main id="ticker-preview-main" className="ticker-preview-main" tabIndex={-1}>
      <h2>Market ticker interaction preview</h2>
      <p>All quotes, timestamps, changes and schedules here are synthetic. No requests to market providers are made.</p>
      <fieldset><legend>Presentation scenario</legend><div className="ticker-scenarios">
        {Object.keys(tickerScenarios).map((name) => <button type="button" key={name} data-scenario={name} aria-pressed={scenario === name} onClick={() => setScenario(name)}>{name}</button>)}
      </div></fieldset>
      <p>Focus the quote strip and use Left/Right or Home/End to scroll. Use Tab to reach instruments and Enter or Space to open their details. Escape or Close returns to the instrument. Clicking outside or moving focus outside dismisses details.</p>
      <p>Movement is manual. Refresh indicators describe supplied model state; these controls simulate presentation states and do not start a refresh timer.</p>
    </main>
  </div>;
}
