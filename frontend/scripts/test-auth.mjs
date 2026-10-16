import assert from "node:assert/strict";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";
import react from "@vitejs/plugin-react";

const server = await createServer({ root: fileURLToPath(new URL("../", import.meta.url)), configFile: false,
  cacheDir: "node_modules/.cache/auth-tests", plugins: [react()], server: { middlewareMode: true, hmr: false, ws: false }, appType: "custom" });
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
  await test("Seed mode pauses all reads; returning to Live clears samples and starts an unconditional read", async () => {
    const { session, time, requests } = sessionSetup();
    try {
      await session.signIn("evaluator", password); await settle();
      assert.equal(session.getSnapshot().dataMode, "live");
      const before = requests.length;
      session.setDataMode("seed");
      const seed = session.getSnapshot();
      assert.equal(seed.dataMode, "seed"); assert.equal(seed.dashboard.snapshot.version, "seed_demo_v1");
      assert.match(seed.dashboard.message, /illustrative.*Not live/);
      assert.equal(Object.keys(seed.dashboard.snapshot.panels).length, 6);
      assert.equal(Object.values(seed.dashboard.snapshot.panels).flatMap(panel => panel.summaries).filter(item => item.value !== null).length, 12);
      assert.equal(seed.dashboard.snapshot.ticker.items.length, 3);
      assert.deepEqual(seed.dashboard.snapshot.observations, {});
      assert.equal(time.pending.size, 1, "Only token expiry should remain scheduled in Seed mode");
      await session.refresh();
      await assert.rejects(session.readIndicator("/indicators", new AbortController().signal), { name: "AbortError" });
      await time.advance(60001);
      assert.equal(requests.length, before, "Seed mode fetched API data");
      session.setDataMode("live");
      assert.equal(session.getSnapshot().dashboard.snapshot, null, "Seed values leaked into Live loading");
      await settle();
      assert.equal(session.getSnapshot().dashboard.snapshot.version, "synthetic_snapshot_1");
      assert.equal(requests.length, before + 1);
      assert.equal(requests.at(-1).options.headers["If-None-Match"], undefined);
      assert.equal(time.pending.size, 2);
      assert.ok(!JSON.stringify(session.getSnapshot()).includes(token));
    } finally { session.dispose(); }
  });
  await test("switching to Seed cancels pending dashboard and panel reads and rejects late responses", async () => {
    let release, captured;
    const { session } = sessionSetup((_url, options) => { captured = options.signal; return new Promise(resolve => { release = resolve; }); });
    try {
      await session.signIn("evaluator", password);
      session.setDataMode("seed");
      assert.equal(captured.aborted, true);
      release(json({ error: { code: "authentication_invalid" } }, 401)); await settle();
      assert.equal(session.getSnapshot().phase, "signed-in");
      assert.equal(session.getSnapshot().dashboard.snapshot.version, "seed_demo_v1");
    } finally { session.dispose(); }
    const setup = sessionSetup((url, options) => url.endsWith("/dashboard") ? json(dashboardFixture()) :
      new Promise(resolve => { captured = options.signal; release = resolve; }));
    try {
      await setup.session.signIn("evaluator", password); await settle();
      const pending = setup.session.readIndicator("/indicators/trade", new AbortController().signal);
      setup.session.setDataMode("seed"); assert.equal(captured.aborted, true);
      release(json({ data: {} }));
      await assert.rejects(pending, { name: "AbortError" });
      assert.equal(setup.session.getSnapshot().dashboard.snapshot.version, "seed_demo_v1");
    } finally { setup.session.dispose(); }
  });
  await test("Seed still expires, clears on logout, and always starts the next session in Live mode", async () => {
    const { session, time } = sessionSetup();
    try {
      await session.signIn("evaluator", password); await settle(); session.setDataMode("seed");
      await time.advance(900001);
      assert.equal(session.getSnapshot().phase, "signed-out");
      assert.equal(session.getSnapshot().dataMode, "live");
      assert.equal(session.getSnapshot().dashboard.snapshot, null);
      session.setDataMode("seed"); assert.equal(session.getSnapshot().dashboard.snapshot, null);
      await session.signIn("evaluator", password); await settle();
      assert.equal(session.getSnapshot().dataMode, "live");
      session.setDataMode("seed"); session.signOut();
      assert.equal(session.getSnapshot().dataMode, "live"); assert.equal(time.pending.size, 0);
    } finally { session.dispose(); }
  });
  await test("repeated mode changes coalesce selections and release previous polling timers", async () => {
    const { session, time, requests } = sessionSetup();
    try {
      await session.signIn("evaluator", password); await settle();
      for (let cycle = 0; cycle < 30; cycle++) {
        const before = requests.length;
        session.setDataMode("seed"); session.setDataMode("seed");
        assert.equal(time.pending.size, 1); assert.equal(requests.length, before);
        session.setDataMode("live"); session.setDataMode("live"); await settle();
        assert.equal(requests.length, before + 1); assert.equal(time.pending.size, 2);
      }
    } finally { session.dispose(); }
    assert.equal(time.pending.size, 0);
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
  await test("login deadline actively cancels a stalled body, clears busy state and permits a fresh manual sign-in", async () => {
    const originalTimeout = AbortSignal.timeout;
    let deadline, started, canceled = false, calls = 0;
    const reading = new Promise((resolve) => { started = resolve; });
    AbortSignal.timeout = (milliseconds) => { assert.equal(milliseconds, 15_000); deadline = new AbortController(); return deadline.signal; };
    try {
      const time = clock();
      const stalled = createAuthSession({ now: time.now, timers: time.timers, transport: async (url) => {
        if (!url.endsWith("/auth/login")) return json(dashboardFixture());
        if (calls++ === 0) return new Response(new ReadableStream({ pull() { started(); }, cancel() { canceled = true; } }, { highWaterMark: 0 }));
        return json(grant());
      } });
      try {
        const pending = stalled.signIn("evaluator", password);
        await reading; deadline.abort(new DOMException("Synthetic deadline", "TimeoutError")); await pending;
        assert.equal(canceled, true); assert.equal(calls, 1);
        assert.equal(stalled.getSnapshot().phase, "signed-out"); assert.equal(time.pending.size, 0);
        assert.equal(stalled.getSnapshot().message.includes(password), false);
        await stalled.signIn("evaluator", password); await settle();
        assert.equal(stalled.getSnapshot().phase, "signed-in"); assert.equal(calls, 2);
      } finally { stalled.dispose(); }
    } finally { AbortSignal.timeout = originalTimeout; }
  });
  await test("caller cancellation and advertised oversized login bodies release their readers without replay", async () => {
    let started, canceled = false;
    const reading = new Promise((resolve) => { started = resolve; }), controller = new AbortController();
    const pending = signInCredentials("evaluator", password, controller.signal, { transport: async () => new Response(new ReadableStream({
      pull() { started(); }, cancel() { canceled = true; },
    }, { highWaterMark: 0 })) });
    await reading; controller.abort(); await assert.rejects(pending, { name: "AbortError" }); assert.equal(canceled, true);
    for (const length of ["16385", "-1", "unknown"]) {
      let canceledHeader = false, calls = 0;
      await assert.rejects(signInCredentials("evaluator", password, new AbortController().signal, { transport: async () => {
        calls++; return new Response(new ReadableStream({ cancel() { canceledHeader = true; } }), { headers: { "Content-Length": length } });
      } }), (error) => error.kind === "invalid");
      assert.equal(canceledHeader, true); assert.equal(calls, 1);
    }
  });
  await test("one hundred login/logout cycles coalesce repeated actions and release all session timers", async () => {
    const { session,time,requests }=sessionSetup();
    let publications=0;
    const unsubscribe=session.subscribe(()=>publications++);
    try {
      for(let cycle=0;cycle<100;cycle++) {
        const before=requests.length;
        await Promise.all(Array.from({length:10},()=>session.signIn("evaluator",password))); await settle();
        assert.equal(requests.length-before,2,"Repeated sign-in spawned extra login/dashboard calls");
        assert.equal(requests.at(-1).options.headers['If-None-Match'],undefined);
        assert.equal(time.pending.size,2,"Session must own only expiry and the next poll");
        await Promise.all(Array.from({length:10},()=>session.refresh()));
        assert.equal(requests.length-before,3,"Repeated refresh spawned duplicate reads");
        session.signOut();
        assert.equal(time.pending.size,0);
        assert.equal(session.getSnapshot().dashboard.snapshot,null);
        await time.advance(60001);
        assert.equal(requests.length-before,3,"Ended session restarted its poll");
      }
      unsubscribe(); const before=publications;
      session.dispose(); assert.equal(publications,before,"Removed subscriber was retained");
    } finally { unsubscribe(); session.dispose(); }
  });
} finally { await server.close(); }
