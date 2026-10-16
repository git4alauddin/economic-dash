// Private test configuration/control arrives on stdin; stdout is redacted JSON only.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { access, mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve, relative, isAbsolute } from "node:path";
import { createInterface } from "node:readline";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import { build, preview } from "vite";
import react from "@vitejs/plugin-react";
import { privateDataBoundary } from "./private-data-boundary.mjs";

const input = createInterface({ input: process.stdin }), lines = input[Symbol.asyncIterator]();
const config = JSON.parse((await lines.next()).value);
const root = fileURLToPath(new URL("../", import.meta.url));
const temporary = await mkdtemp(join(tmpdir(), "economic-dash-browser-"));
const site = join(temporary, "site"), profile = join(temporary, "profile");
let browser, socket, web;
const pending = new Map(), requests = [], network = [], statuses = [], errors = [];
async function waitFor(probe, description, timeout = 15000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) { if (await probe()) return; await delay(50); }
  throw new Error(`Timed out: ${description}`);
}
try {
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
    if (item.method === "Runtime.exceptionThrown") errors.push(item.params.exceptionDetails.text);
    if (item.method === "Network.requestWillBeSent") network.push(item.params.request.url);
    if (item.method === "Network.webSocketCreated") network.push(item.params.url);
    if (item.method === "Network.requestWillBeSent" && item.params.type === "Fetch") {
      const request = item.params.request;
      requests.push({ url: request.url, method: request.method, authenticated: !!request.headers.Authorization,
        conditional: !!request.headers["If-None-Match"] });
    }
    if (item.method === "Network.responseReceived" && item.params.response.url === `${config.api_url}/api/v1/dashboard`) statuses.push(item.params.response.status);
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
  await command("Page.enable"); await command("Runtime.enable"); await command("Network.enable");
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
  await signIn("incorrect synthetic password");
  await visible(`!!document.querySelector('[role="alert"]') && !document.querySelector('#username').disabled`, "generic credential failure");
  assert.equal(await evaluate(`document.querySelector('#password').value`), "");
  assert.equal(requests.filter((r) => r.url.endsWith("/auth/login")).length, 1);
  await signIn(); await dashboard();
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
  assert.equal(requests.filter((r) => r.url.endsWith("/auth/login")).length, loginCount, "Password was replayed after a data error");
  await command("Network.setBlockedURLs", { urls: [] });
  await click("Refresh data"); await dashboard();
  await click("Sign out");
  await visible(`!!document.querySelector('#username')&&!document.querySelector('[data-dashboard-root]')`, "logout clears data");
  const beforeSignIn = requests.length;
  await signIn(); await dashboard();
  const fresh = requests.slice(beforeSignIn).find((r) => r.url.endsWith("/dashboard"));
  assert.ok(fresh?.authenticated && !fresh.conditional, "New session reused previous protected validator");
  await command("Page.reload", { ignoreCache: true });
  await visible(`!!document.querySelector('#username')&&!document.querySelector('[data-dashboard-root]')`, "reload requires sign-in");
  await signIn(); await dashboard();
  await control("disable");
  await click("Refresh data");
  await visible(`!!document.querySelector('#username')&&!document.querySelector('[data-dashboard-root]')`, "real revoked-account 401 clears data");
  assert.ok(statuses.includes(401));
  await control("enable");
  await signIn(); await dashboard();
  await command("Emulation.setVirtualTimePolicy", { policy: "pauseIfNetworkFetchesPending", budget: 901000, maxVirtualTimeTaskStarvationCount: 100 });
  await visible(`!!document.querySelector('#username')&&document.querySelector('[role="alert"]')?.textContent.includes('expired')`, "client expiry clears session");
  assert.equal(await evaluate(`!!document.querySelector('[data-dashboard-root]')`), false);
  assert.equal(errors.length, 0, "Browser runtime exception");
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
    network_boundary_verified: true }) + "\n");
} finally {
  input.close();
  for (const callback of pending.values()) clearTimeout(callback.timer);
  socket?.close();
  if (browser && browser.exitCode === null) {
    await new Promise((accept) => { const timer = setTimeout(() => { browser.kill(); accept(); }, 3000); browser.once("exit", () => { clearTimeout(timer); accept(); }); });
  }
  if (web) await new Promise((accept) => web.httpServer.close(accept));
  const child = relative(resolve(tmpdir()), resolve(temporary));
  if (!child.startsWith("..") && !isAbsolute(child) && child.startsWith("economic-dash-browser-")) await rm(temporary, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
}
