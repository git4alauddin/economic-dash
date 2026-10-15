import type { UiState } from "../../ui/types";

const messages: Record<UiState, string> = {
  loading: "Loading…", fresh: "Up to date", stale: "Stale data",
  empty: "No observations in this period", error: "Unable to load data", unavailable: "Data unavailable",
};

export default function StateMessage({ state, detail, announce = false }: { state: UiState; detail?: string; announce?: boolean }) {
  return (
    <div className={`state-message state-${state}`} data-state={state} role={announce ? state === "error" ? "alert" : "status" : undefined}>
      <span className="state-dot" aria-hidden="true" />
      <div><strong>{messages[state]}</strong>{detail && <p>{detail}</p>}</div>
    </div>
  );
}
