import { apiBaseUrl } from "../config";
import { acceptDashboard, failDashboard, type DashboardView } from "./dashboard-state";
import type { DashboardSnapshot } from "./dashboard-contract";
import { ContractError } from "./validate";

export type DashboardTransport = (url: string, options: RequestInit) => Promise<Response>;
export class DashboardReadError extends Error {
  constructor(public readonly kind: "network" | "invalid" | "unauthorized") { super("Dashboard request failed."); }
}
type ReadResult = { unchanged: true; etag: string | null } | { unchanged: false; etag: string | null; body: unknown };
const validEtag = (value: string | null) => value && value.length <= 256 && /^(?:W\/)?"[\x21\x23-\x7E]*"$/.test(value) ? value : null;
async function fetchDashboard(signal: AbortSignal, token: string, transport: DashboardTransport, etag: string | null = null): Promise<ReadResult> {
  signal.throwIfAborted();
  if (!token.trim()) throw new DashboardReadError("unauthorized");
  const requestSignal = AbortSignal.any([signal, AbortSignal.timeout(15_000)]);
  try {
    const headers: Record<string, string> = { Accept: "application/json", Authorization: `Bearer ${token}` };
    if (etag) headers["If-None-Match"] = etag;
    const response = await transport(`${apiBaseUrl}/api/v1/dashboard`, { method: "GET", headers, credentials: "omit", cache: "no-store", redirect: "error", signal: requestSignal });
    requestSignal.throwIfAborted();
    if (response.status === 401 || response.status === 403) throw new DashboardReadError("unauthorized");
    if (response.status === 304) return { unchanged: true, etag: validEtag(response.headers.get("ETag")) };
    if (!response.ok) throw new DashboardReadError("network");
    const body = await response.text();
    requestSignal.throwIfAborted();
    if (body.length > 2_000_000) throw new DashboardReadError("invalid");
    try { return { unchanged: false, body: JSON.parse(body) as unknown, etag: validEtag(response.headers.get("ETag")) }; } catch { throw new DashboardReadError("invalid"); }
  } catch (error) {
    signal.throwIfAborted();
    throw error instanceof DashboardReadError ? error : new DashboardReadError("network");
  }
}
// Single reads remain available; conditional polling owns its cache explicitly below.
export async function readDashboard(signal: AbortSignal, token: string, transport: DashboardTransport = fetch): Promise<unknown> {
  const result = await fetchDashboard(signal, token, transport);
  if (result.unchanged) throw new DashboardReadError("invalid");
  return result.body;
}
export async function loadDashboard(previous: DashboardSnapshot | null, signal: AbortSignal, token: string, transport?: DashboardTransport): Promise<DashboardView> {
  try { return acceptDashboard(await readDashboard(signal, token, transport)); }
  catch (error) {
    signal.throwIfAborted();
    return failDashboard(previous, error instanceof DashboardReadError ? error.kind : error instanceof ContractError ? "invalid" : "network");
  }
}

export interface DashboardPollResult { view: DashboardView; unchanged: boolean; unauthorized: boolean; }
export function createDashboardReader(transport: DashboardTransport = fetch) {
  let snapshot: DashboardSnapshot | null = null, etag: string | null = null, owner: string | null = null, generation = 0;
  function clear() { snapshot = null; etag = null; owner = null; generation++; }
  async function read(signal: AbortSignal, token: string): Promise<DashboardPollResult> {
    if (owner !== token) { clear(); owner = token; }
    const attempt = ++generation;
    const current = () => { signal.throwIfAborted(); if (attempt !== generation) throw new DOMException("Request superseded", "AbortError"); };
    try {
      const result = await fetchDashboard(signal, token, transport, etag);
      current();
      if (result.unchanged) {
        if (!snapshot || !etag || !result.etag || result.etag.replace(/^W\//, "") !== etag.replace(/^W\//, "")) throw new DashboardReadError("invalid");
        return { view: { phase: "ready", snapshot, message: "Dashboard checked; no changes." }, unchanged: true, unauthorized: false };
      }
      const view = acceptDashboard(result.body);
      current();
      snapshot = view.snapshot; etag = result.etag;
      return { view, unchanged: false, unauthorized: false };
    } catch (error) {
      current();
      const kind = error instanceof DashboardReadError ? error.kind : error instanceof ContractError ? "invalid" : "network";
      const view = failDashboard(snapshot, kind);
      etag = null; snapshot = view.snapshot;
      return { view, unchanged: false, unauthorized: kind === "unauthorized" };
    }
  }
  return { read, clear };
}
