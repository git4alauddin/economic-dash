import assert from "node:assert/strict";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";
import react from "@vitejs/plugin-react";

const server = await createServer({ root: fileURLToPath(new URL("../", import.meta.url)), configFile: false,
  cacheDir: "node_modules/.cache/auth-tests", plugins: [react()], server: { middlewareMode: true, hmr: false }, appType: "custom" });
try {
  const { signInCredentials } = await server.ssrLoadModule("/src/auth/auth-client.ts");
  const { createAuthSession } = await server.ssrLoadModule("/src/auth/session.ts");
  const { dashboardFixture } = await server.ssrLoadModule("/src/preview/dashboard-fixtures.ts");
  const { default: SignInScreen } = await server.ssrLoadModule("/src/components/SignInScreen.tsx");
  const { default: App } = await server.ssrLoadModule("/src/App.tsx");
  const json = (body, status = 200, headers = {}) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
  const password = "synthetic auth test passphrase", token = "fixture.payload.signature";
  const start = Date.parse("2026-10-16T10:00:00Z");
  const grant = (now = start, seconds = 900) => ({ access_token: token, token_type: "bearer", expires_in: seconds,
    expires_at: new Date(now + seconds * 1000).toISOString(), user: { user_id: "1".repeat(32), username: "evaluator" } });
  const settle = async () => { for (let i = 0; i < 5; i++) await new Promise(setImmediate); };
  function clock() {
    let at = start, next = 0;
    const pending = new Map();
    return { now: () => at, pending,
      timers: { schedule(fn, delay) { const id = ++next; pending.set(id, { fn, due: at + delay }); return id; }, cancel(id) { pending.delete(id); } },
      async advance(ms) {
        at += ms;
        for (let guard = 0; guard < 30; guard++) {
          const entry = [...pending].find(([, timer]) => timer.due <= at);
          if (!entry) break;
          pending.delete(entry[0]); entry[1].fn(); await settle();
        }
      },
      jump(ms) { at += ms; },
    };
  }
  function sessionSetup(respond = () => json(dashboardFixture(), 200, { ETag: 'W/"one"' })) {
    const time = clock(), requests = [];
    const session = createAuthSession({ now: time.now, timers: time.timers, transport: async (url, options) => {
      requests.push({ url, options });
      return url.endsWith("/auth/login") ? json(grant(time.now())) : respond(url, options);
    } });
    return { session, time, requests };
  }

  await test("login sends credentials once in a bounded JSON POST, never cookies or URL parameters", async () => {
    let count = 0;
    const result = await signInCredentials("Evaluator", password, new AbortController().signal, { now: () => start, transport: async (url, options) => {
      count++;
      assert.ok(url.endsWith("/api/v1/auth/login"));
      assert.equal(new URL(url).search, "");
      assert.equal(options.method, "POST"); assert.equal(options.credentials, "omit");
      assert.equal(options.cache, "no-store"); assert.equal(options.redirect, "error");
      assert.deepEqual(JSON.parse(options.body), { username: "Evaluator", password });
      assert.equal(options.headers.Authorization, undefined);
      return json(grant());
    } });
    assert.equal(count, 1); assert.equal(result.token, token); assert.equal(result.lifetimeMs, 900000);
  });
  await test("login classifies failures without echoing server text or retrying credentials", async () => {
    for (const [status, kind] of [[401, "credentials"], [403, "credentials"], [429, "rate-limited"], [503, "unavailable"], [422, "invalid"]]) {
      let count = 0;
      await assert.rejects(signInCredentials("evaluator", password, new AbortController().signal, { transport: async () => {
        count++; return new Response(password, { status });
      } }), (error) => error.kind === kind && !error.message.includes(password));
      assert.equal(count, 1);
    }
    await assert.rejects(signInCredentials("evaluator", password, new AbortController().signal, { transport: async () => { throw Error(password); } }), (error) => error.kind === "network" && !error.message.includes(password));
  });
  await test("malformed, oversized, expired or wrong-type login responses cannot establish a session", async () => {
    for (const changes of [{ token_type: "cookie" }, { expires_in: true }, { expires_in: 1801 }, { access_token: "invalid" },
      { expires_at: "2026-02-30T10:00:00Z" }, { expires_at: new Date(start - 1).toISOString() }, { user: { user_id: "bad", username: "evaluator" } }]) {
      await assert.rejects(signInCredentials("evaluator", password, new AbortController().signal, { now: () => start, transport: async () => json({ ...grant(), ...changes }) }), (error) => error.kind === "invalid");
    }
    for (const body of ["not-json", "x".repeat(16385)]) await assert.rejects(signInCredentials("evaluator", password, new AbortController().signal,
      { now: () => start, transport: async () => new Response(body) }), (error) => error.kind === "invalid");
  });
  await test("the signed-out app renders labelled login controls and no dashboard data", () => {
    const html = renderToStaticMarkup(createElement(App));
    assert.ok(html.includes('for="username"') && html.includes('for="password"'));
    assert.ok(html.includes('type="password"') && html.includes('autoComplete="current-password"'));
    assert.ok(!html.includes("data-dashboard-root") && !html.includes("session-toolbar"));
    const pending = renderToStaticMarkup(createElement(SignInScreen, { busy: true, message: "", onSignIn: async () => {} }));
    assert.ok(pending.includes('aria-busy="true"') && pending.includes("Signing in"));
  });
  await test("sign-in loads the dashboard then polls in sixty seconds, with token kept out of public state", async () => {
    const { session, time, requests } = sessionSetup();
    try {
      assert.equal(requests.length, 0);
      await session.signIn("evaluator", password); await settle();
      assert.equal(session.getSnapshot().phase, "signed-in");
      assert.ok(session.getSnapshot().dashboard.snapshot);
      assert.equal(requests.length, 2);
      assert.equal(requests[1].options.headers.Authorization, `Bearer ${token}`);
      assert.ok(!JSON.stringify(session.getSnapshot()).includes(token));
      assert.ok(!JSON.stringify(session.getSnapshot()).includes(password));
      await time.advance(59999); assert.equal(requests.length, 2);
      await time.advance(1); assert.equal(requests.length, 3);
      session.signOut();
      assert.equal(session.getSnapshot().dashboard.snapshot, null);
      assert.equal(time.pending.size, 0);
      await time.advance(60000); assert.equal(requests.length, 3);
    } finally { session.dispose(); }
  });
  await test("401 and 403 during polling clear the session and stop all timers", async () => {
    for (const status of [401, 403]) {
      let failing = false;
      const { session, time } = sessionSetup(() => failing ? new Response(null, { status }) : json(dashboardFixture()));
      try {
        await session.signIn("evaluator", password); await settle(); failing = true;
        await session.refresh();
        assert.equal(session.getSnapshot().phase, "signed-out");
        assert.equal(session.getSnapshot().user, null);
        assert.equal(session.getSnapshot().dashboard.snapshot, null);
        assert.equal(time.pending.size, 0);
      } finally { session.dispose(); }
    }
  });
  await test("expiry and resume checks clear data without waiting for the next network poll", async () => {
    for (const resume of [false, true]) {
      const { session, time } = sessionSetup();
      try {
        await session.signIn("evaluator", password); await settle();
        if (resume) { time.jump(900001); session.checkExpiry(); }
        else await time.advance(900000);
        assert.equal(session.getSnapshot().phase, "signed-out");
        assert.ok(session.getSnapshot().message.includes("expired"));
        assert.equal(session.getSnapshot().dashboard.snapshot, null);
        assert.equal(time.pending.size, 0);
      } finally { session.dispose(); }
    }
  });
  await test("network failure retains only permitted stale values and a manual retry recovers", async () => {
    let fail = false;
    const { session } = sessionSetup(() => { if (fail) throw Error("offline"); return json(dashboardFixture()); });
    try {
      await session.signIn("evaluator", password); await settle(); fail = true;
      await session.refresh();
      assert.equal(session.getSnapshot().phase, "signed-in");
      assert.ok(session.getSnapshot().dashboard.message.includes("stale"));
      fail = false; await session.refresh();
      assert.equal(session.getSnapshot().dashboard.phase, "ready");
      assert.ok(!session.getSnapshot().refreshing);
    } finally { session.dispose(); }
  });
  await test("sign-out cancels an unfinished login and a late response cannot restore the session", async () => {
    const time = clock(); let respond, signal, requests = 0;
    const session = createAuthSession({ now: time.now, timers: time.timers, transport: async (_url, options) => {
      requests++; signal = options.signal; return new Promise((resolve) => { respond = resolve; });
    } });
    const pending = session.signIn("evaluator", password);
    await session.signIn("evaluator", password); assert.equal(requests, 1);
    session.signOut(); assert.ok(signal.aborted);
    respond(json(grant())); await pending; await settle();
    assert.equal(session.getSnapshot().phase, "signed-out");
    assert.equal(time.pending.size, 0);
  });
  await test("sign-out cancels pending dashboard reads and a new page starts signed out", async () => {
    let respond, signal;
    const { session, time } = sessionSetup((_url, options) => { signal = options.signal; return new Promise((resolve) => { respond = resolve; }); });
    await session.signIn("evaluator", password);
    session.signOut(); assert.ok(signal.aborted);
    respond(json(dashboardFixture())); await settle();
    assert.equal(session.getSnapshot().phase, "signed-out");
    assert.equal(session.getSnapshot().dashboard.snapshot, null);
    assert.equal(time.pending.size, 0);
    const reloaded = createAuthSession();
    assert.equal(reloaded.getSnapshot().phase, "signed-out"); reloaded.dispose();
  });
  await test("period/history reads share bearer limits, reject foreign paths and abort on logout", async () => {
    let finish, signal;
    const { session, requests } = sessionSetup((url, options) => {
      if (!url.includes("/indicators")) return json(dashboardFixture());
      signal = options.signal; return new Promise((resolve) => { finish = resolve; });
    });
    await assert.rejects(session.readIndicator("/indicators?window=24", new AbortController().signal));
    assert.equal(requests.length, 0);
    await session.signIn("evaluator", password); await settle();
    await assert.rejects(session.readIndicator("https://example.invalid/indicators", new AbortController().signal));
    assert.equal(requests.length, 2);
    const pending = session.readIndicator("/indicators/gdp_growth?window=10&period=gdp_growth_world%3ACY2024", new AbortController().signal);
    const request = requests.at(-1);
    assert.equal(request.options.headers.Authorization, `Bearer ${token}`);
    assert.equal(request.options.credentials, "omit"); assert.equal(request.options.redirect, "error");
    assert.equal(request.url.includes(token), false); assert.equal(JSON.stringify(session.getSnapshot()).includes(token), false);
    session.signOut(); assert.equal(signal.aborted, true);
    finish(json(dashboardFixture())); await assert.rejects(pending);
    assert.equal(session.getSnapshot().dashboard.snapshot, null); session.dispose();
  });
  await test("401/403 from lazy catalog or historical selection clear the whole session", async () => {
    for (const status of [401, 403]) {
      const { session, time } = sessionSetup((url) => url.includes("/indicators") ? json({}, status) : json(dashboardFixture()));
      await session.signIn("evaluator", password); await settle();
      await assert.rejects(session.readIndicator("/indicators?window=24", new AbortController().signal));
      assert.equal(session.getSnapshot().phase, "signed-out"); assert.equal(time.pending.size, 0); session.dispose();
    }
  });
} finally { await server.close(); }
