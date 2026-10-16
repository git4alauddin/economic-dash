import { apiBaseUrl } from "../config";
import type { DashboardTransport } from "../data/dashboard-client";

export interface SessionUser { userId: string; username: string; }
export interface LoginGrant { token: string; user: SessionUser; expiresAt: number; lifetimeMs: number; }
export class SignInError extends Error {
  constructor(public readonly kind: "credentials" | "network" | "unavailable" | "rate-limited" | "invalid") { super("Sign-in request failed."); }
}
const object = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new SignInError("invalid");
  return value as Record<string, unknown>;
};

async function boundedJson(response: Response): Promise<unknown> {
  if (!response.body) throw new SignInError("invalid");
  const reader = response.body.getReader(), parts: Uint8Array[] = [];
  let size = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 16_384) { await reader.cancel(); throw new SignInError("invalid"); }
      parts.push(value);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const part of parts) { bytes.set(part, offset); offset += part.byteLength; }
    try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown; }
    catch { throw new SignInError("invalid"); }
  } finally { reader.releaseLock(); }
}

export async function signInCredentials(username: string, password: string, signal: AbortSignal,
  { transport = fetch, now = Date.now }: { transport?: DashboardTransport; now?: () => number } = {}): Promise<LoginGrant> {
  signal.throwIfAborted();
  if (!username.trim() || username.length > 128 || !password || password.length > 128) throw new SignInError("credentials");
  const requestSignal = AbortSignal.any([signal, AbortSignal.timeout(15_000)]);
  try {
    const response = await transport(`${apiBaseUrl}/api/v1/auth/login`, { method: "POST", credentials: "omit", cache: "no-store", redirect: "error",
      headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify({ username, password }), signal: requestSignal });
    requestSignal.throwIfAborted();
    if (response.status === 401 || response.status === 403) throw new SignInError("credentials");
    if (response.status === 429) throw new SignInError("rate-limited");
    if (response.status >= 500) throw new SignInError("unavailable");
    if (!response.ok) throw new SignInError("invalid");
    const data = object(await boundedJson(response)), user = object(data.user);
    requestSignal.throwIfAborted();
    const token = data.access_token, expiresAt = typeof data.expires_at === "string" ? Date.parse(data.expires_at) : NaN;
    const receivedAt = now();
    if (typeof token !== "string" || token.length > 4096 || !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(token)
      || data.token_type !== "bearer" || !Number.isInteger(data.expires_in) || (data.expires_in as number) < 1 || (data.expires_in as number) > 1800
      || !Number.isFinite(expiresAt) || typeof data.expires_at !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/.test(data.expires_at)
      || new Date(expiresAt).toISOString().slice(0, 19) !== data.expires_at.slice(0, 19) || expiresAt <= receivedAt
      || typeof user.user_id !== "string" || !/^[0-9a-f]{32}$/.test(user.user_id)
      || typeof user.username !== "string" || !/^[a-z][a-z0-9_.-]{2,63}$/.test(user.username)) throw new SignInError("invalid");
    return { token, user: { userId: user.user_id, username: user.username }, expiresAt,
      lifetimeMs: Math.min(expiresAt - receivedAt, (data.expires_in as number) * 1000) };
  } catch (error) {
    signal.throwIfAborted();
    throw error instanceof SignInError ? error : new SignInError("network");
  }
}
