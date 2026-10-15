import { useEffect, useState } from "react";
import DashboardScreen from "../components/DashboardScreen";
import { loadDashboard, type DashboardTransport } from "../data/dashboard-client";
import { acceptDashboard, beginRefresh } from "../data/dashboard-state";
import { dashboardFixture, responseFixture, stateScenarioNames, type StateScenario } from "./dashboard-fixtures";

export default function StatesPreview() {
  const [scenario, setScenario] = useState<StateScenario>("fresh");
  const [view, setView] = useState(() => acceptDashboard(dashboardFixture()));
  useEffect(() => {
    const controller = new AbortController();
    const fixture = dashboardFixture(scenario !== "no-retention");
    if (scenario === "mixed-retention") {
      fixture.data.panels.gdp_growth.series.gdp_growth_world.latest.retention_allowed = false;
      fixture.data.panels.gdp_growth.series.gdp_growth_india.history.points[1].retention_allowed = false;
      fixture.data.ticker.items[0].retention_allowed = false;
    }
    const previous = ["fresh", "retained", "no-retention", "mixed-retention", "unauthorized"].includes(scenario) ? acceptDashboard(fixture).snapshot : null;
    setView(beginRefresh(previous));
    const transport: DashboardTransport = async (_url, options) => {
      await new Promise<void>((resolve, reject) => {
        if (options.signal?.aborted) { reject(new DOMException("Aborted", "AbortError")); return; }
        const timer = scenario === "loading" ? undefined : setTimeout(resolve, 60);
        options.signal?.addEventListener("abort", () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); }, { once: true });
      });
      if (scenario === "unauthorized") return new Response(null, { status: 401 });
      if (["error", "retained", "no-retention", "mixed-retention"].includes(scenario)) return new Response(null, { status: 503 });
      return new Response(scenario === "malformed" ? "{invalid json" : JSON.stringify(responseFixture(scenario)), { status: 200 });
    };
    void loadDashboard(previous, controller.signal, "synthetic-preview-token", transport).then((next) => {
      if (!controller.signal.aborted) setView(next);
    }).catch(() => { /* Canceled scenario requests must not replace the new selection. */ });
    return () => controller.abort();
  }, [scenario]);
  return <div data-states-preview data-scenario={scenario} data-view-phase={view.phase}>
    <DashboardScreen view={view} preview />
    <label className="state-preview-control">Synthetic API state
      <select aria-label="Synthetic API state" value={scenario} onChange={(event) => setScenario(event.target.value as StateScenario)}>
        {stateScenarioNames.map((name) => <option key={name}>{name}</option>)}
      </select>
    </label>
  </div>;
}
