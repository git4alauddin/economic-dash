import { apiBaseUrl } from "../config";
import { acceptDashboard, failDashboard, type DashboardView } from "./dashboard-state";
import type { DashboardSnapshot } from "./dashboard-contract";
import { ContractError } from "./validate";

export type DashboardTransport = (url: string, options: RequestInit) => Promise<Response>;
export class DashboardReadError extends Error {
  constructor(public readonly kind: "network" | "invalid" | "unauthorized") { super("Dashboard request failed."); }
}
// M5 supplies an in-memory token. No persistent storage, upstream URLs or polling.
export async function readDashboard(signal: AbortSignal, token: string, transport: DashboardTransport = fetch): Promise<unknown> {
  signal.throwIfAborted();
  if (!token.trim()) throw new DashboardReadError("unauthorized");
  const requestSignal = AbortSignal.any([signal, AbortSignal.timeout(15_000)]);
  try {
    const response = await transport(`${apiBaseUrl}/api/v1/dashboard`, { method: "GET", headers: { Accept: "application/json", Authorization: `Bearer ${token}` }, credentials: "omit", cache: "no-store", redirect: "error", signal: requestSignal });
    requestSignal.throwIfAborted();
    if (response.status === 401 || response.status === 403) throw new DashboardReadError("unauthorized");
    if (!response.ok) throw new DashboardReadError("network");
    const body = await response.text();
    requestSignal.throwIfAborted();
    if (body.length > 2_000_000) throw new DashboardReadError("invalid");
    try { return JSON.parse(body) as unknown; } catch { throw new DashboardReadError("invalid"); }
  } catch (error) {
    signal.throwIfAborted();
    throw error instanceof DashboardReadError ? error : new DashboardReadError("network");
  }
}
export async function loadDashboard(previous: DashboardSnapshot | null, signal: AbortSignal, token: string, transport?: DashboardTransport): Promise<DashboardView> {
  try { return acceptDashboard(await readDashboard(signal, token, transport)); }
  catch (error) {
    signal.throwIfAborted();
    return failDashboard(previous, error instanceof DashboardReadError ? error.kind : error instanceof ContractError ? "invalid" : "network");
  }
}
