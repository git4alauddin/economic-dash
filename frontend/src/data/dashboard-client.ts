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
async function boundedDashboardJson(response: Response, signal: AbortSignal): Promise<unknown> {
  const limit = 2_000_000, length = response.headers.get("Content-Length");
  if (length !== null && (!/^\d{1,10}$/.test(length) || Number(length) > limit)) {
    void response.body?.cancel().catch(() => {});
    throw new DashboardReadError("invalid");
  }
  if (!response.body) throw new DashboardReadError("invalid");
  const reader = response.body.getReader(), parts: Uint8Array[] = [];
  const cancel = () => { void reader.cancel().catch(() => {}); };
  signal.addEventListener("abort", cancel, { once: true });
  let size = 0;
  try {
    signal.throwIfAborted();
    for (;;) {
      const { done, value } = await reader.read();
      signal.throwIfAborted();
      if (done) break;
      size += value.byteLength;
      if (size > limit) { cancel(); throw new DashboardReadError("invalid"); }
      parts.push(value);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const part of parts) { bytes.set(part, offset); offset += part.byteLength; }
    try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown; }
    catch { throw new DashboardReadError("invalid"); }
  } finally {
    signal.removeEventListener("abort", cancel);
    reader.releaseLock();
  }
}
async function fetchDashboard(signal: AbortSignal, token: string, transport: DashboardTransport, etag: string | null = null, path = "/dashboard"): Promise<ReadResult> {
  signal.throwIfAborted();
  if (!token.trim()) throw new DashboardReadError("unauthorized");
  const requestSignal = AbortSignal.any([signal, AbortSignal.timeout(15_000)]);
  try {
    const headers: Record<string, string> = { Accept: "application/json", Authorization: `Bearer ${token}` };
    if (etag) headers["If-None-Match"] = etag;
    const response = await transport(`${apiBaseUrl}/api/v1${path}`, { method: "GET", headers, credentials: "omit", cache: "no-store", redirect: "error", signal: requestSignal });
    requestSignal.throwIfAborted();
    if (response.status === 401 || response.status === 403) throw new DashboardReadError("unauthorized");
    if (response.status === 304) return { unchanged: true, etag: validEtag(response.headers.get("ETag")) };
    if (!response.ok) throw new DashboardReadError("network");
    const body = await boundedDashboardJson(response, requestSignal);
    requestSignal.throwIfAborted();
    return { unchanged: false, body, etag: validEtag(response.headers.get("ETag")) };
  } catch (error) {
    signal.throwIfAborted();
    throw error instanceof DashboardReadError ? error : new DashboardReadError("network");
  }
}
// Same origin, bearer transport, byte limit and deadline as dashboard polling.
export async function readIndicatorResource(path: string, signal: AbortSignal, token: string, transport: DashboardTransport = fetch): Promise<unknown> {
  if (!/^\/indicators(?:\/[a-z_]+)?(?:\?[a-zA-Z0-9_%=&:+.-]*)?$/.test(path)) throw new DashboardReadError("invalid");
  const result = await fetchDashboard(signal, token, transport, null, path);
  if (result.unchanged) throw new DashboardReadError("invalid");
  return result.body;
}
// Single reads remain available; conditional polling owns its cache explicitly below.
export async function readDashboard(signal: AbortSignal, token: string, transport: DashboardTransport = fetch): Promise<unknown> {
  const result = await fetchDashboard(signal, token, transport);
  if (result.unchanged) throw new DashboardReadError("invalid");
  return result.body;
}
export async function loadDashboard(previous: DashboardSnapshot | null, signal: AbortSignal, token: string, transport?: DashboardTransport): Promise<DashboardView> {
  try { return acceptDashboard(await readDashboard(signal, token, transport), previous); }
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
      const view = acceptDashboard(result.body, snapshot);
      current();
      snapshot = view.snapshot;
      const invalid = snapshot!.issues.some((issue) => issue.includes("invalid") || issue.endsWith(": unavailable"))
        || Object.values(snapshot!.observations).some((entries) => Object.values(entries).some((item) => item.validationIssues?.length));
      etag = invalid ? null : result.etag;
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
