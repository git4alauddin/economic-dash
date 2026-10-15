import { useEffect, useState } from "react";
import { checkApiConnection } from "./api";

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
    loading: "Loading…",
    ready: "The dashboard is coming soon.",
    error: "Unable to load the dashboard. Please try again later.",
  }[status];

  return (
    <main>
      <h1>Economic Indicators Dashboard</h1>
      <p role={status === "error" ? "alert" : "status"}>{message}</p>
    </main>
  );
}
