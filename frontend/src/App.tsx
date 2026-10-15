import { useEffect, useState } from "react";
import { checkApiConnection } from "./api";
import DashboardLayout from "./components/DashboardLayout";
import { indicatorPanelComponents } from "./components/panels/IndicatorPanels";

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

  return (
    <DashboardLayout apiState={status} announcement={message}>
      {indicatorPanelComponents.map((Panel, index) => <Panel key={index} state={status === "ready" ? "unavailable" : status} />)}
    </DashboardLayout>
  );
}
