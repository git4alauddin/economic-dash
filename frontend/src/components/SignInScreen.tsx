import { useEffect, useRef, type FormEvent } from "react";

export default function SignInScreen({ busy, message, onSignIn }: { busy: boolean; message: string; onSignIn(username: string, password: string): Promise<void> }) {
  const username = useRef<HTMLInputElement>(null), password = useRef<HTMLInputElement>(null);
  useEffect(() => { if (!busy) (username.current?.value ? password.current : username.current)?.focus(); }, [busy]);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const name = username.current?.value ?? "", secret = password.current?.value ?? "";
    if (password.current) password.current.value = "";
    void onSignIn(name, secret);
  }
  return <main className="sign-in-page">
    <section className="sign-in-card" aria-labelledby="sign-in-title">
      <p className="sign-in-brand">Economic Indicators Dashboard</p>
      <h1 id="sign-in-title">Sign in to your dashboard</h1>
      <p className="sign-in-intro">Use your evaluator account to view economic indicators.</p>
      <form onSubmit={submit} aria-busy={busy} aria-describedby="session-note">
        <label htmlFor="username">Username</label>
        <input id="username" ref={username} name="username" autoComplete="username" autoCapitalize="none" spellCheck={false} required maxLength={128} disabled={busy} />
        <label htmlFor="password">Password</label>
        <input id="password" ref={password} name="password" type="password" autoComplete="current-password" required maxLength={128} disabled={busy} />
        {message && <p className="sign-in-message" role="alert">{message}</p>}
        <button className="sign-in-submit" type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        <span className="sr-only" role="status">{busy ? "Signing in. Please wait." : ""}</span>
      </form>
      <p id="session-note" className="session-note">Your session stays in this tab. Reloading the page requires sign-in.</p>
    </section>
  </main>;
}
