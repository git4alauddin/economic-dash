import { spawn } from "node:child_process";
import { access, mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const options = new Map();
for (let index = 2; index < process.argv.length; index += 2) {
  const key = process.argv[index];
  if (!["--url", "--output", "--browser"].includes(key) || !process.argv[index + 1]) {
    throw new Error("Use --url <frontend URL>, --output <directory>, --browser <Chrome/Edge executable>.");
  }
  options.set(key, process.argv[index + 1]);
}
const url = new URL(options.get("--url") ?? "http://127.0.0.1:5173/").href;
const cache = join(frontendRoot, "node_modules/.cache/layout-check");
const output = resolve(options.get("--output") ?? join(cache, "results"));
await mkdir(cache, { recursive: true });
await mkdir(output, { recursive: true });

const browserCandidates = [
  options.get("--browser"), process.env.CHROME_PATH,
  join(process.env.ProgramFiles ?? "C:/Program Files", "Google/Chrome/Application/chrome.exe"),
  join(process.env["ProgramFiles(x86)"] ?? "C:/Program Files (x86)", "Microsoft/Edge/Application/msedge.exe"),
].filter(Boolean);
let executable;
for (const candidate of browserCandidates) {
  try { await access(candidate); executable = candidate; break; } catch { /* Try the next installed browser. */ }
}
if (!executable) throw new Error("Set CHROME_PATH or --browser to an installed Chrome/Edge executable.");
const frontendResponse = await fetch(url, { signal: AbortSignal.timeout(5000) });
if (!frontendResponse.ok) throw new Error(`Frontend returned HTTP ${frontendResponse.status}. Start Vite first.`);

const profile = await mkdtemp(join(cache, "browser-"));
const browser = spawn(executable, [
  "--headless=new", "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
  `--user-data-dir=${profile}`, "--no-first-run", "--no-default-browser-check",
  "--disable-background-networking", "--disable-extensions", "about:blank",
], { windowsHide: true, stdio: ["ignore", "ignore", "pipe"] });
let launchError;
browser.on("error", (error) => { launchError = error; });
// Drain browser diagnostics without flooding the terminal.
browser.stderr.resume();

async function waitFor(probe, description, timeout = 15000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (launchError) throw launchError;
    if (browser.exitCode !== null) throw new Error(`Browser exited with code ${browser.exitCode}.`);
    const value = await probe();
    if (value) return value;
    await delay(100);
  }
  throw new Error(`Timed out waiting for ${description}.`);
}

let socket;
let command;
const report = { url, checkedAt: new Date().toISOString(), viewports: [] };
const runtimeErrors = [];
const fetchUrls = new Set();
try {
  const portFile = await waitFor(async () => {
    try { return await readFile(join(profile, "DevToolsActivePort"), "utf8"); } catch { return null; }
  }, "the isolated browser debugging port");
  const port = Number(portFile.split("\n")[0]);
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const target = targets.find((entry) => entry.type === "page");
  if (!target) throw new Error("No browser page target available.");
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((accept, reject) => {
    socket.addEventListener("open", accept, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  let nextId = 0;
  const pending = new Map();
  socket.addEventListener("message", ({ data }) => {
    const message = JSON.parse(data);
    if (message.method === "Runtime.exceptionThrown") {
      runtimeErrors.push(message.params.exceptionDetails.exception?.description ?? message.params.exceptionDetails.text);
    }
    if (message.method === "Network.requestWillBeSent" && message.params.type === "Fetch") fetchUrls.add(message.params.request.url);
    const request = pending.get(message.id);
    if (!request) return;
    clearTimeout(request.timer);
    pending.delete(message.id);
    if (message.error) request.reject(new Error(message.error.message));
    else request.accept(message.result);
  });
  socket.addEventListener("close", () => {
    for (const request of pending.values()) {
      clearTimeout(request.timer);
      request.reject(new Error("Browser connection closed."));
    }
    pending.clear();
  });
  command = (method, params = {}) => new Promise((accept, reject) => {
    const id = ++nextId;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`Browser command timed out: ${method}`));
    }, 15000);
    pending.set(id, { accept, reject, timer });
    socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) => {
    const result = await command("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
  };
  await command("Page.enable");
  await command("Runtime.enable");
  await command("Network.enable");
  await command("Page.addScriptToEvaluateOnNewDocument", { source: `
    window.layoutShiftScore = 0;
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (!entry.hadRecentInput) window.layoutShiftScore += entry.value;
      }
    }).observe({ type: 'layout-shift', buffered: true });
  ` });

  for (const viewport of [
    { name: "target", width: 1214, height: 2159 },
    { name: "narrow", width: 390, height: 844 },
    { name: "compact", width: 320, height: 740 },
    { name: "api-offline", width: 1214, height: 2159, offline: true },
  ]) {
    runtimeErrors.length = 0;
    await command("Emulation.setDeviceMetricsOverride", { width: viewport.width, height: viewport.height, deviceScaleFactor: 1, mobile: false });
    if (viewport.offline) {
      if (!fetchUrls.size) throw new Error("No API request observed for the offline check.");
      await command("Network.setBlockedURLs", { urls: [...fetchUrls] });
    }
    const previousTimeOrigin = await evaluate("performance.timeOrigin");
    const navigation = await command("Page.navigate", { url });
    if (navigation.errorText) throw new Error(navigation.errorText);
    await waitFor(() => evaluate(`Boolean(performance.timeOrigin !== ${previousTimeOrigin} && document.readyState === 'complete' && document.querySelector('[data-dashboard-root]') && document.querySelector('[data-dashboard-root]').dataset.apiState !== 'loading')`), "the new dashboard ready/error state");
    await evaluate("document.fonts.ready.then(() => true)");
    await delay(150);
    const measurements = await evaluate(`(${inspectLayout.toString()})()`);
    const issues = [];
    if (measurements.viewportWidth !== viewport.width || measurements.viewportHeight !== viewport.height) issues.push("Unexpected CSS viewport");
    if (measurements.documentWidth > measurements.layoutWidth) issues.push("Document has horizontal overflow");
    if (measurements.clippedHeadings) issues.push("Heading text is clipped");
    if (measurements.panels.length !== 6) issues.push("Expected six indicator regions");
    if (measurements.panels.map((panel) => panel.id).join(",") !== "gdp_growth,debt_to_gdp,trade,gst_collection,inflation_india,government_expenditure") issues.push("Panel order differs from reference");
    if (measurements.layoutShiftScore > 0.01) issues.push("Unexpected initial layout shift");
    if (runtimeErrors.length) issues.push("Browser JavaScript exceptions");
    if (viewport.offline && measurements.apiState !== "error") issues.push("Expected API failure state");
    for (const panel of measurements.panels) {
      if (panel.x < 0 || panel.right > measurements.layoutWidth || panel.clipped) issues.push(`Clipped panel: ${panel.id}`);
    }
    if (viewport.width === 1214) {
      // Independent approximate PNG audit bounds; tolerance allows raster/font rounding.
      const baseline = [[29, 158], [619, 158], [29, 710], [619, 710], [29, 1263], [619, 1263]];
      measurements.panels.forEach((panel, index) => {
        const expected = baseline[index];
        if (!expected || Math.abs(panel.x - expected[0]) > 4 || Math.abs(panel.y - expected[1]) > 4 || Math.abs(panel.width - 566.5) > 4 || Math.abs(panel.height - 529) > 4) {
          issues.push(`Panel geometry differs from reference: ${panel.id}`);
        }
        if (panel.bottom > viewport.height) issues.push(`Panel falls below target screen: ${panel.id}`);
      });
    } else if (new Set(measurements.panels.map((panel) => Math.round(panel.x))).size !== 1) {
      issues.push("Narrow layout must have one column");
    }
    const screenshot = await command("Page.captureScreenshot", {
      format: "png", clip: { x: 0, y: 0, width: viewport.width, height: viewport.height, scale: 1 }, captureBeyondViewport: true,
    });
    await writeFile(join(output, `${viewport.name}.png`), Buffer.from(screenshot.data, "base64"));
    report.viewports.push({ ...viewport, ...measurements, runtimeErrors: [...runtimeErrors], issues });
    console.log(`${issues.length ? "FAIL" : "PASS"} ${viewport.name} ${viewport.width}x${viewport.height}: overflow=${Math.max(0, measurements.documentWidth - measurements.layoutWidth)}px, layoutShift=${measurements.layoutShiftScore}`);
  }
  await writeFile(join(output, "layout-report.json"), `${JSON.stringify(report, null, 2)}\n`);
  if (report.viewports.some((entry) => entry.issues.length)) throw new Error(`Layout checks failed. See ${join(output, "layout-report.json")}`);
  console.log(`Evidence: ${output}`);
} finally {
  if (socket?.readyState === WebSocket.OPEN) {
    await command("Browser.close").catch(() => {});
    socket.close();
  }
  // Only the isolated browser started above is stopped; never attach to a user's browser.
  if (browser.exitCode === null) browser.kill();
}

function inspectLayout() {
  return {
    viewportWidth: innerWidth,
    viewportHeight: innerHeight,
    layoutWidth: document.documentElement.clientWidth,
    documentWidth: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
    apiState: document.querySelector("[data-dashboard-root]").dataset.apiState,
    layoutShiftScore: window.layoutShiftScore,
    clippedHeadings: [...document.querySelectorAll(".dashboard-header h1, .panel-heading h2")].some((heading) => {
      const bounds = heading.getBoundingClientRect();
      return bounds.x < 0 || bounds.right > document.documentElement.clientWidth || heading.scrollWidth > heading.clientWidth + 1 || heading.scrollHeight > heading.clientHeight + 1;
    }),
    panels: [...document.querySelectorAll("[data-panel-id]")].map((panel) => {
      const bounds = panel.getBoundingClientRect();
      const heading = panel.querySelector("h2");
      return {
        id: panel.dataset.panelId,
        x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height,
        right: bounds.right, bottom: bounds.bottom,
        clipped: panel.scrollWidth > panel.clientWidth + 1 || panel.scrollHeight > panel.clientHeight + 1 || heading.scrollWidth > heading.clientWidth + 1,
      };
    }),
  };
}
