import { signInCredentials, SignInError, type SessionUser } from "./auth-client";
import { startDashboardPolling } from "../data/dashboard-poller";
import { DashboardReadError, readIndicatorResource, type DashboardTransport } from "../data/dashboard-client";
import { beginRefresh, initialDashboardView, type DashboardView } from "../data/dashboard-state";

export interface SessionSnapshot {
  phase: "signed-out" | "signing-in" | "signed-in";
  user: SessionUser | null;
  message: string;
  dashboard: DashboardView;
  refreshing: boolean;
}
interface Timers { schedule(callback: () => void, delay: number): unknown; cancel(handle: unknown): void; }
const messages = {
  credentials: "Username or password is incorrect.", network: "Unable to reach the service. Check your connection and try again.",
  unavailable: "Sign-in is temporarily unavailable. Please try again.", "rate-limited": "Too many sign-in attempts. Please wait before trying again.",
  invalid: "Unable to validate the sign-in response. Please try again.",
};

// Tokens and pending credentials stay inside this controller, never a store/URL/cookie.
export function createAuthSession({ transport, now = Date.now, timers = {
  schedule: (callback: () => void, delay: number) => globalThis.setTimeout(callback, delay),
  cancel: (handle: unknown) => globalThis.clearTimeout(handle as ReturnType<typeof globalThis.setTimeout>),
} }: { transport?: DashboardTransport; now?: () => number; timers?: Timers } = {}) {
  let snapshot: SessionSnapshot = { phase: "signed-out", user: null, message: "", dashboard: initialDashboardView, refreshing: false };
  const listeners = new Set<() => void>();
  let generation = 0, expiresAt = 0, expiryTimer: unknown = null;
  let pendingLogin: AbortController | null = null;
  let token = "", lifetime = new AbortController();
  let polling: ReturnType<typeof startDashboardPolling> | null = null;
  function publish(value: SessionSnapshot) { snapshot = value; listeners.forEach((listener) => listener()); }
  function end(message: string) {
    generation++; pendingLogin?.abort(); pendingLogin = null;
    token = ""; lifetime.abort(); lifetime = new AbortController();
    polling?.stop(); polling = null; expiresAt = 0;
    if (expiryTimer !== null) timers.cancel(expiryTimer);
    expiryTimer = null;
    publish({ phase: "signed-out", user: null, message, dashboard: initialDashboardView, refreshing: false });
  }
  function checkExpiry() {
    if (snapshot.phase === "signed-in" && now() >= expiresAt) end("Your session expired. Please sign in again.");
  }
  function expireWhenDue(id: number) {
    expiryTimer = timers.schedule(() => {
      expiryTimer = null;
      if (id !== generation || snapshot.phase !== "signed-in") return;
      checkExpiry();
      if (id === generation && snapshot.phase === "signed-in") expireWhenDue(id);
    }, Math.max(1, expiresAt - now()));
  }
  async function signIn(username: string, password: string) {
    if (snapshot.phase === "signing-in") return;
    end("");
    const id = generation, controller = new AbortController();
    pendingLogin = controller;
    publish({ ...snapshot, phase: "signing-in", message: "" });
    try {
      const grant = await signInCredentials(username, password, controller.signal, { transport, now });
      if (id !== generation || controller.signal.aborted) return;
      expiresAt = Math.min(grant.expiresAt, now() + grant.lifetimeMs);
      token = grant.token;
      publish({ phase: "signed-in", user: grant.user, message: "", dashboard: initialDashboardView, refreshing: true });
      expireWhenDue(id);
      polling = startDashboardPolling(grant.token, (dashboard) => {
        if (id !== generation || snapshot.phase !== "signed-in") return;
        checkExpiry();
        if (id === generation && snapshot.phase === "signed-in") publish({ ...snapshot, dashboard, refreshing: false });
      }, { transport, timers, onUnauthorized: () => { if (id === generation) end("Your session ended. Please sign in again."); } });
    } catch (error) {
      if (id === generation && !controller.signal.aborted) end(messages[error instanceof SignInError ? error.kind : "network"]);
    } finally { if (id === generation) pendingLogin = null; }
  }
  return {
    getSnapshot: () => snapshot,
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    signIn, signOut: () => end("You have signed out."), checkExpiry,
    async readIndicator(path: string, signal: AbortSignal): Promise<unknown> {
      checkExpiry();
      if (snapshot.phase !== "signed-in") throw new DashboardReadError("unauthorized");
      const id = generation, combined = AbortSignal.any([signal, lifetime.signal]);
      try {
        const result = await readIndicatorResource(path, combined, token, transport);
        combined.throwIfAborted(); checkExpiry();
        if (id !== generation) throw new DOMException("Session ended", "AbortError");
        return result;
      } catch (error) {
        if (id === generation && !combined.aborted && error instanceof DashboardReadError && error.kind === "unauthorized") end("Your session ended. Please sign in again.");
        throw error;
      }
    },
    async refresh() {
      checkExpiry();
      if (snapshot.phase !== "signed-in" || snapshot.refreshing) return;
      publish({ ...snapshot, dashboard: beginRefresh(snapshot.dashboard.snapshot), refreshing: true });
      await polling?.refresh().catch(() => {});
    },
    dispose: () => end(""),
  };
}
