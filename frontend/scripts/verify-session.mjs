// Private test configuration/control arrives on stdin; stdout is redacted JSON only.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { access, mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve, relative, isAbsolute } from "node:path";
import { createInterface } from "node:readline";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import { build, preview, createServer } from "vite";
import react from "@vitejs/plugin-react";
import { privateDataBoundary } from "./private-data-boundary.mjs";

const input = createInterface({ input: process.stdin }), lines = input[Symbol.asyncIterator]();
const config = JSON.parse((await lines.next()).value);
const root = fileURLToPath(new URL("../", import.meta.url));
const temporary = await mkdtemp(join(tmpdir(), "economic-dash-browser-"));
const site = join(temporary, "site"), profile = join(temporary, "profile");
let browser, socket, web, validator;
const pending = new Map(), requests = [], network = [], statuses = [], errors = [];
const dashboardRequests = new Set(), dashboardBodies = [], captures = [];
const indicatorRequests = new Map(), indicatorBodies = [];
const runtimeErrors = new Map();
async function waitFor(probe, description, timeout = 15000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) { if (await probe()) return; await delay(50); }
  throw new Error(`Timed out: ${description}`);
}
try {
  validator = await createServer({ root, configFile: false, cacheDir: "node_modules/.cache/session-validator", server: { middlewareMode: true, hmr: false }, appType: "custom" });
  const { formatValue } = await validator.ssrLoadModule("/src/ui/format.ts");
  const { panelBindings } = await validator.ssrLoadModule("/src/data/dashboard-contract.ts");
  await build({ root, configFile: false, publicDir: false, plugins: [react(), privateDataBoundary(root)], logLevel: "error",
    define: { "import.meta.env.VITE_API_BASE_URL": JSON.stringify(config.api_url) }, build: { outDir: site, emptyOutDir: true } });
  web = await preview({ root, configFile: false, logLevel: "error", build: { outDir: site },
    preview: { host: "127.0.0.1", port: config.frontend_port, strictPort: true } });
  const candidates = [process.env.CHROME_PATH,
    join(process.env.ProgramFiles ?? "C:/Program Files", "Google/Chrome/Application/chrome.exe"),
    join(process.env["ProgramFiles(x86)"] ?? "C:/Program Files (x86)", "Microsoft/Edge/Application/msedge.exe")].filter(Boolean);
  let executable;
  for (const candidate of candidates) { try { await access(candidate); executable = candidate; break; } catch {} }
  assert.ok(executable, "An installed Chrome/Edge browser is required");
  browser = spawn(executable, ["--headless=new", "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
    `--user-data-dir=${profile}`, "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
    "--disable-extensions", "--disable-save-password-bubble", "about:blank"], { windowsHide: true, stdio: ["ignore", "ignore", "pipe"] });
  browser.stderr.resume();
  let launchError;
  browser.on("error", (error) => { launchError = error; });
  let port;
  await waitFor(async () => {
    if (launchError) throw launchError;
    if (browser.exitCode !== null) throw Error("Isolated browser exited during startup");
    try { port = Number((await readFile(join(profile, "DevToolsActivePort"), "utf8")).split("\n")[0]); return !!port; } catch { return false; }
  }, "browser startup");
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(targets.find((target) => target.type === "page").webSocketDebuggerUrl);
  await new Promise((accept, reject) => { socket.addEventListener("open", accept, { once: true }); socket.addEventListener("error", reject, { once: true }); });
  let id = 0;
  socket.addEventListener("message", ({ data }) => {
    const item = JSON.parse(data);
    if (item.method === "Runtime.exceptionThrown") {
      const detail = item.params.exceptionDetails;
      runtimeErrors.set(detail.exceptionId, { text: detail.text, kind: detail.exception?.className,
        frames: detail.stackTrace?.callFrames.map(({ functionName, lineNumber }) => ({ functionName, lineNumber })) });
    }
    if (item.method === "Runtime.exceptionRevoked") runtimeErrors.delete(item.params.exceptionId);
    if (item.method === "Network.requestWillBeSent") network.push(item.params.request.url);
    if (item.method === "Network.webSocketCreated") network.push(item.params.url);
    if (item.method === "Network.requestWillBeSent" && item.params.type === "Fetch") {
      const request = item.params.request;
      requests.push({ url: request.url, method: request.method, authenticated: !!request.headers.Authorization,
        conditional: !!request.headers["If-None-Match"] });
    }
    if (item.method === "Network.responseReceived" && item.params.type === "Fetch" && item.params.response.url === `${config.api_url}/api/v1/dashboard`) {
      statuses.push(item.params.response.status);
      // Only the first full response is needed for the source trace. Later
      // responses can disappear during intentional reload/logout/cancellation.
      if (item.params.response.status === 200 && captures.length === 0) dashboardRequests.add(item.params.requestId);
    }
    if (item.method === "Network.loadingFinished" && dashboardRequests.delete(item.params.requestId)) {
      captures.push(command("Network.getResponseBody", { requestId: item.params.requestId }).then((result) => {
        dashboardBodies.push(JSON.parse(result.base64Encoded ? Buffer.from(result.body, "base64").toString("utf8") : result.body));
      }).catch(() => { errors.push("Dashboard response capture failed"); }));
    }
    if (item.method === "Network.responseReceived" && item.params.type === "Fetch" && item.params.response.status === 200 && item.params.response.url.startsWith(`${config.api_url}/api/v1/indicators`)) {
      indicatorRequests.set(item.params.requestId, item.params.response.url);
    }
    if (item.method === "Network.loadingFinished" && indicatorRequests.has(item.params.requestId)) {
      const url = indicatorRequests.get(item.params.requestId); indicatorRequests.delete(item.params.requestId);
      captures.push(command("Network.getResponseBody", { requestId: item.params.requestId }).then((result) => {
        indicatorBodies.push({ url, body: JSON.parse(result.base64Encoded ? Buffer.from(result.body, "base64").toString("utf8") : result.body) });
      }).catch(() => { errors.push("Indicator response capture failed"); }));
    }
    const callback = pending.get(item.id);
    if (callback) { clearTimeout(callback.timer); pending.delete(item.id); item.error ? callback.reject(Error(item.error.message)) : callback.accept(item.result); }
  });
  const command = (method, params = {}) => new Promise((accept, reject) => {
    const next = ++id, timer = setTimeout(() => { pending.delete(next); reject(Error(`Browser command timeout: ${method}`)); }, 15000);
    pending.set(next, { accept, reject, timer }); socket.send(JSON.stringify({ id: next, method, params }));
  });
  const evaluate = async (expression) => {
    const result = await command("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw Error("Browser evaluation failed");
    return result.result.value;
  };
  const visible = (expression, label) => waitFor(() => evaluate(expression), label);
  const click = (label) => evaluate(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent===${JSON.stringify(label)})?.click()`);
  const signIn = async (password = config.password) => {
    await visible(`!!document.querySelector('#username:not(:disabled)')`, "enabled login");
    await evaluate(`document.querySelector('#username').value=${JSON.stringify(config.username)};document.querySelector('#password').value=${JSON.stringify(password)};document.querySelector('form').requestSubmit();true`);
  };
  const dashboard = () => visible(`!!document.querySelector('[data-dashboard-root]') && !!Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Refresh data'&&!b.disabled)`, "loaded dashboard");
  const control = async (action) => {
    process.stdout.write(JSON.stringify({ control: action }) + "\n");
    assert.equal(JSON.parse((await lines.next()).value).ok, true);
  };
  const assertWorldTrace = async (expectedState) => {
    const expected = config.world_trace;
    const dom = await evaluate(`(() => {
      const panel=document.querySelector('[data-panel-id="gdp_growth"]');
      const details=panel.querySelector('.panel-data-details');
      if(!details.open) details.querySelector('summary').click();
      const series=Array.from(details.querySelectorAll('section')).find(section=>section.querySelector('h3')?.textContent.startsWith('World '));
      const footer=series.querySelector('.source-as-of');
      const row=Array.from(series.querySelectorAll('tbody tr')).find(row=>row.querySelector('th').textContent===${JSON.stringify(expected.period.label)});
      return {display:panel.querySelector('.summary-value[aria-label="World"] .summary-number').textContent,
        date:footer.lastElementChild.textContent.trim(),links:Array.from(footer.querySelectorAll('a')).map(a=>({name:a.textContent,url:a.href})),
        nonNse:footer.querySelectorAll('.source-tag').length,history:row?.querySelector('td').textContent,
        state:series.getAttribute('data-series-state'),visible:footer.getBoundingClientRect().height>0};
    })()`);
    assert.equal(dom.display, expected.display, "Rendered World GDP differs from publisher/SQL value");
    assert.equal(dom.history, expected.display, "World history row differs from publisher/SQL value");
    assert.equal(dom.date, `Period ending ${expected.year}`, "World as-of precision/date changed");
    assert.deepEqual(dom.links, expected.sources.map(({ name, url }) => ({ name, url })), "World publisher links changed");
    assert.equal(dom.nonNse, expected.sources.length);
    assert.equal(dom.state, expectedState);
    assert.equal(dom.visible, true, "World source/date details are not visible");
    await evaluate(`document.querySelector('[data-panel-id="gdp_growth"] .panel-data-details').open=false`);
  };
  const assertPanelBinding = async (id, raw) => {
    const expected = panelBindings[id].summaries.map((sid) => {
      const item = sid ? raw.series[sid] : null;
      return item ? formatValue(["fresh", "stale"].includes(item.latest.status) ? item.latest.value : null, item.latest.unit, item.precision) : "—";
    });
    const actual = await evaluate(`Array.from(document.querySelector('[data-panel-id="${id}"]').querySelectorAll('.summary-number')).map(node=>node.textContent)`);
    assert.deepEqual(actual, expected, `${id} summary binding mismatch`);
    for (const [sid, series] of Object.entries(raw.series)) {
      const dom = await evaluate(`(() => {
        const section=document.querySelector('[data-panel-id="${id}"] [data-series-id="${sid}"]');
        return {rows:Array.from(section.querySelectorAll('tbody tr')).map(row=>[row.querySelector('th').textContent,row.querySelector('td').textContent]),
          links:Array.from(section.querySelectorAll('a')).map(a=>({name:a.textContent,url:a.href})),state:section.dataset.seriesState};
      })()`);
      assert.deepEqual(dom.rows, series.history.points.map((point) => [point.observation_period.label, formatValue(point.value, point.unit, series.precision)]), `${id}/${sid} history binding mismatch`);
      const sources = [...new Map([series.latest, ...series.history.points].flatMap((point) => point.sources).map((source) => [source.source_id, source])).values()];
      assert.deepEqual(dom.links, sources.map(({ name, url }) => ({ name, url })), `${id}/${sid} source mismatch`);
      assert.equal(dom.state, series.latest.status);
      if (series.comparison && series.latest.value !== null) {
        const text = await evaluate(`document.querySelector('[data-panel-id="${id}"]').textContent`);
        assert.ok(text.includes(series.comparison.reference_label), `${id} comparison reference lost`);
      }
    }
  };
  const verifyPanelInteractions = async (panels) => {
    for (const [id, raw] of Object.entries(panels)) {
      const selector = `[data-panel-id="${id}"]`;
      await evaluate(`document.querySelector('${selector} .panel-data-details').open=true`);
      await visible(`!!document.querySelector('${selector} select[data-period-series]')`, `${id} verified period choices`);
      await assertPanelBinding(id, raw);
      for (const sid of Object.keys(raw.series)) {
        const disabled = await evaluate(`document.querySelector('${selector} [data-period-series="${sid}"]').disabled`);
        const options = await evaluate(`Array.from(document.querySelector('${selector} [data-period-series="${sid}"]').options).slice(1).map(option=>option.value)`);
        const catalog = indicatorBodies.find((entry) => new URL(entry.url).pathname === "/api/v1/indicators")?.body;
        assert.ok(catalog, "Catalog response not captured");
        const choice = catalog.data.find((panel) => panel.indicator_id === id).series.find((item) => item.series_id === sid);
        assert.deepEqual(options, choice.available_periods.map((period) => period.id));
        assert.equal(disabled, choice.status === "blocked" || !choice.available_periods.length);
      }
      const before = indicatorBodies.length;
      await evaluate(`(() => {const select=document.querySelector('${selector} select[aria-label="History window"]');select.value='10';select.dispatchEvent(new Event('change',{bubbles:true}));})()`);
      await visible(`document.querySelector('${selector} [role="status"]')?.textContent.startsWith('Selected history.')`, `${id} history window`);
      await waitFor(() => indicatorBodies.slice(before).some((entry) => new URL(entry.url).pathname === `/api/v1/indicators/${id}`), `${id} panel response`);
      let selected = indicatorBodies.slice(before).findLast((entry) => new URL(entry.url).pathname === `/api/v1/indicators/${id}`);
      assert.equal(new URL(selected.url).searchParams.get("window"), "10");
      await assertPanelBinding(id, selected.body.data);
      const sid = Object.keys(raw.series).find((key) => selected.body.data.series[key].history.points.some((point) => point.value !== null));
      if (sid) {
        const period = await evaluate(`document.querySelector('${selector} [data-period-series="${sid}"]').options[1].value`);
        const count = indicatorBodies.length;
        await evaluate(`(() => {const select=document.querySelector('${selector} [data-period-series="${sid}"]');select.value=${JSON.stringify(period)};select.dispatchEvent(new Event('change',{bubbles:true}));})()`);
        await visible(`document.querySelector('${selector} [role="status"]')?.textContent.startsWith('Selected history.')`, `${id} historical period`);
        await waitFor(() => indicatorBodies.slice(count).some((entry) => new URL(entry.url).searchParams.getAll("period").includes(`${sid}:${period}`)), `${id} selected-period query`);
        selected = indicatorBodies.slice(count).findLast((entry) => new URL(entry.url).pathname === `/api/v1/indicators/${id}`);
        assert.equal(selected.body.data.series[sid].latest.observation_period.id, period);
        await assertPanelBinding(id, selected.body.data);
        await click("Refresh data"); await dashboard();
        assert.equal(await evaluate(`document.querySelector('${selector} [data-period-series="${sid}"]').value`), period, "Latest poll overwrote historical selection");
        await assertPanelBinding(id, selected.body.data);
      }
      await evaluate(`Array.from(document.querySelectorAll('${selector} button')).find(button=>button.textContent==='Latest view').click()`);
      await assertPanelBinding(id, raw);
      // Real plotted points retain keyboard inspection and Escape dismissal.
      const points = await evaluate(`document.querySelectorAll('${selector} .chart-point').length`);
      if (points) {
        await evaluate(`document.querySelector('${selector} .chart-point').focus()`);
        try { await visible(`!!document.querySelector('${selector} [role="tooltip"]')`, `${id} focused point tooltip`, 2000); }
        catch {
          const diagnostic = await evaluate(`(() => { const point=document.querySelector('${selector} .chart-point');return {active:document.activeElement?.tagName,activeClass:document.activeElement?.getAttribute('class'),focused:document.activeElement===point,tabindex:point.getAttribute('tabindex'),pageFocus:document.hasFocus(),rect:point.getBoundingClientRect().toJSON(),figure:point.closest('figure').textContent.slice(-180)};})()`);
          throw Error(`${id} chart focus failed: ${JSON.stringify(diagnostic)}`);
        }
        await command("Input.dispatchKeyEvent", { type: "keyDown", key: "End", code: "End" });
        assert.equal(await evaluate(`document.activeElement===Array.from(document.querySelectorAll('${selector} .chart-point')).at(-1)`), true);
        await command("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape" });
        assert.equal(await evaluate(`!!document.querySelector('${selector} [role="tooltip"]')`), false);
      }
      await evaluate(`document.querySelector('${selector} .panel-data-details summary').focus()`);
      await command("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape" });
      assert.equal(await evaluate(`document.querySelector('${selector} .panel-data-details').open`), false);
    }
    assert.ok(await evaluate(`document.querySelector('[data-panel-id="debt_to_gdp"] .summary-value[aria-label="Ind vs US"]').textContent.includes('Comparison definition unresolved.')`));
    for (const quote of dashboardBodies[0].data.ticker.items) {
      await evaluate(`document.querySelector('[data-instrument-id="${quote.instrument_id}"]').click()`);
      assert.ok(await evaluate(`!!document.querySelector('.ticker-details')`));
      assert.ok(await evaluate(`document.querySelector('.ticker-details').textContent.includes('Quote unavailable')`));
      await click("Close");
      assert.equal(await evaluate(`document.activeElement.getAttribute('data-instrument-id')`), quote.instrument_id);
    }
  };
  await command("Page.enable"); await command("Runtime.enable"); await command("Network.enable");
  // Headless pages can have an active SVG element while the page itself is
  // unfocused, suppressing native focus events. Emulate the foreground tab.
  await command("Emulation.setFocusEmulationEnabled", { enabled: true });
  await command("Emulation.setDeviceMetricsOverride", { width: 1214, height: 2159, deviceScaleFactor: 1, mobile: false });
  await command("Page.addScriptToEvaluateOnNewDocument", { source: `
    for(const name of ['localStorage','sessionStorage']) Object.defineProperty(window,name,{get(){throw Error('Storage disabled for session check')}});
    Object.defineProperty(document,'cookie',{get(){return ''},set(){throw Error('Cookies disabled for session check')}});
  ` });
  await command("Page.navigate", { url: `http://127.0.0.1:${config.frontend_port}/` });
  await visible(`!!document.querySelector('#username')`, "signed-out page");
  assert.equal(requests.length, 0, "Signed-out UI fetched protected data");
  assert.equal(await evaluate(`document.activeElement.id`), "username");
  assert.equal(await evaluate(`document.querySelector('#password').type`), "password");
  assert.equal(await evaluate(`fetch(${JSON.stringify(config.api_url + "/api/v1/dashboard")},{credentials:'omit',cache:'no-store'}).then(response=>response.status)`), 401,
    "Direct unauthenticated browser request reached protected data");
  await signIn("incorrect synthetic password");
  await visible(`!!document.querySelector('[role="alert"]') && !document.querySelector('#username').disabled`, "generic credential failure");
  assert.equal(await evaluate(`document.querySelector('#password').value`), "");
  assert.equal(requests.filter((r) => r.url.endsWith("/auth/login")).length, 1);
  await signIn(); await dashboard();
  await waitFor(() => dashboardBodies.length > 0, "actual dashboard response capture");
  const world = dashboardBodies[0].data.panels.gdp_growth.series.gdp_growth_world.latest;
  for (const field of ["value", "unit", "definition_id", "vintage_id", "sources"]) assert.deepEqual(world[field], config.world_trace[field], "Publisher/SQL/API World trace mismatch");
  assert.deepEqual(world.observation_period, config.world_trace.period);
  assert.equal(world.as_of, config.world_trace.year);
  assert.equal(world.as_of_precision, "year");
  await assertWorldTrace(world.status);
  await verifyPanelInteractions(dashboardBodies[0].data.panels);
  assert.equal(await evaluate(`document.querySelector('.indicator-grid').children.length`), 6);
  assert.ok(await evaluate(`document.querySelectorAll('a[href^="https://"]').length>0`), "Real publisher attribution was lost");
  assert.equal((await command("Network.getCookies")).cookies.length, 0);
  await command("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: false });
  assert.ok(await evaluate(`document.documentElement.scrollWidth<=window.innerWidth`), "Narrow dashboard overflows");
  await command("Emulation.setDeviceMetricsOverride", { width: 1214, height: 2159, deviceScaleFactor: 1, mobile: false });
  await click("Refresh data"); await dashboard();
  await waitFor(() => statuses.includes(304), "conditional refresh");
  const loginCount = requests.filter((r) => r.url.endsWith("/auth/login")).length;
  await command("Network.setBlockedURLs", { urls: [`${config.api_url}/*`] });
  await click("Refresh data");
  await visible(`document.querySelector('.dashboard-feedback')?.textContent.includes('stale')`, "offline retained state");
  assert.ok(await evaluate(`!!document.querySelector('[data-dashboard-root]')`));
  await assertWorldTrace("stale");
  assert.equal(requests.filter((r) => r.url.endsWith("/auth/login")).length, loginCount, "Password was replayed after a data error");
  await command("Network.setBlockedURLs", { urls: [] });
  await click("Refresh data"); await dashboard();
  await assertWorldTrace(world.status);
  await click("Sign out");
  await visible(`!!document.querySelector('#username')&&!document.querySelector('[data-dashboard-root]')`, "logout clears data");
  const beforeSignIn = requests.length;
  await signIn(); await dashboard();
  const fresh = requests.slice(beforeSignIn).find((r) => r.url.endsWith("/dashboard"));
  assert.ok(fresh?.authenticated && !fresh.conditional, "New session reused previous protected validator");
  await command("Page.reload", { ignoreCache: true });
  await visible(`!!document.querySelector('#username')&&!document.querySelector('[data-dashboard-root]')`, "reload requires sign-in");
  await signIn(); await dashboard();
  const unauthorizedBeforeRevocation = statuses.filter((status) => status === 401).length;
  await control("disable");
  await click("Refresh data");
  await visible(`!!document.querySelector('#username')&&!document.querySelector('[data-dashboard-root]')`, "real revoked-account 401 clears data");
  assert.ok(statuses.filter((status) => status === 401).length > unauthorizedBeforeRevocation);
  await control("enable");
  await signIn(); await dashboard();
  await command("Emulation.setVirtualTimePolicy", { policy: "pauseIfNetworkFetchesPending", budget: 901000, maxVirtualTimeTaskStarvationCount: 100 });
  await visible(`!!document.querySelector('#username')&&document.querySelector('[role="alert"]')?.textContent.includes('expired')`, "client expiry clears session");
  assert.equal(await evaluate(`!!document.querySelector('[data-dashboard-root]')`), false);
  await Promise.all(captures);
  assert.equal(errors.length, 0, "Browser response capture failed");
  assert.equal(runtimeErrors.size, 0, "Unhandled browser exceptions: " + JSON.stringify([...runtimeErrors.values()]));
  assert.ok(requests.every((r) => r.url.startsWith(config.api_url + "/api/v1/")), "Browser contacted an unexpected data source");
  const frontendOrigin = `http://127.0.0.1:${config.frontend_port}`;
  assert.ok(network.length > 0 && network.every((url) => {
    const parsed = new URL(url);
    if (parsed.origin === frontendOrigin) return parsed.pathname === "/" || parsed.pathname.startsWith("/assets/") || parsed.pathname === "/favicon.ico";
    return parsed.origin === config.api_url && parsed.pathname.startsWith("/api/v1/");
  }), "Browser network escaped the static frontend/authenticated API boundary");
  await command("Browser.close");
  process.stdout.write(JSON.stringify({ result: "PASS", scenarios: 10, panels: 6, web_storage_disabled: true,
    cookies_disabled: true, real_revocation_verified: true, expiry_verified: true, no_runtime_errors: true,
    network_boundary_verified: true, world_source_sql_api_ui_verified: true,
    world_failure_recovery_verified: true, direct_unauthorized_rejected: true, full_dashboard_interactions_verified: true }) + "\n");
} finally {
  input.close();
  for (const callback of pending.values()) clearTimeout(callback.timer);
  socket?.close();
  if (browser && browser.exitCode === null) {
    await new Promise((accept) => { const timer = setTimeout(() => { browser.kill(); accept(); }, 3000); browser.once("exit", () => { clearTimeout(timer); accept(); }); });
  }
  if (web) await new Promise((accept) => web.httpServer.close(accept));
  await validator?.close();
  const child = relative(resolve(tmpdir()), resolve(temporary));
  if (!child.startsWith("..") && !isAbsolute(child) && child.startsWith("economic-dash-browser-")) await rm(temporary, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
}
