import { createDashboardReader, type DashboardTransport } from "./dashboard-client";
import type { DashboardView } from "./dashboard-state";

export const DASHBOARD_POLL_INTERVAL_MS = 60_000;
interface Timers { schedule(callback: () => void, delay: number): unknown; cancel(handle: unknown): void; }
const browserTimers: Timers = {
  schedule: (callback, delay) => globalThis.setTimeout(callback, delay),
  cancel: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof globalThis.setTimeout>),
};

// M5 starts this after sign-in and calls stop on logout/unmount. No token is invented.
export function startDashboardPolling(token: string, onView: (view: DashboardView) => void,
  { transport, timers = browserTimers }: { transport?: DashboardTransport; timers?: Timers } = {}) {
  const reader = createDashboardReader(transport), controller = new AbortController();
  let stopped = false, pending: Promise<void> | null = null, timer: unknown = null;
  function stop() {
    stopped = true; controller.abort(); reader.clear();
    if (timer !== null) timers.cancel(timer);
    timer = null;
  }
  function refresh(): Promise<void> {
    if (stopped) return Promise.resolve();
    if (pending) return pending;
    if (timer !== null) { timers.cancel(timer); timer = null; }
    pending = (async () => {
      try {
        const result = await reader.read(controller.signal, token);
        if (!stopped) {
          if (result.unauthorized) stop();
          onView(result.view);
        }
      } finally {
        pending = null;
        if (!stopped) timer = timers.schedule(() => { void refresh().catch(() => {}); }, DASHBOARD_POLL_INTERVAL_MS);
      }
    })();
    return pending;
  }
  void refresh().catch(() => {});
  return { refresh, stop };
}
