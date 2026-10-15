import { spawn } from "node:child_process";
import { access, mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const options = new Map();
for (let index = 2; index < process.argv.length; index += 2) {
  const key = process.argv[index];
  if (!["--url", "--output", "--browser", "--mode"].includes(key) || !process.argv[index + 1]) {
    throw new Error("Use --url <frontend URL>, --output <directory>, --browser <executable>, --mode dashboard|primitives|panels|ticker|states.");
  }
  options.set(key, process.argv[index + 1]);
}
const mode = options.get("--mode") ?? "dashboard";
if (!["dashboard", "primitives", "panels", "ticker", "states"].includes(mode)) throw new Error("Unknown verification mode.");
const targetUrl = new URL(options.get("--url") ?? "http://127.0.0.1:5173/");
if (mode === "primitives" && targetUrl.pathname === "/") targetUrl.pathname = "/__ui-preview";
if (mode === "panels" && targetUrl.pathname === "/") targetUrl.pathname = "/__panel-preview";
if (mode === "ticker" && targetUrl.pathname === "/") targetUrl.pathname = "/__ticker-preview";
if (mode === "states" && targetUrl.pathname === "/") targetUrl.pathname = "/__states-preview";
const url = targetUrl.href;
const cache = join(frontendRoot, "node_modules/.cache/layout-check");
const output = resolve(options.get("--output") ?? join(cache, mode === "dashboard" ? "results" : mode));
const reportName = mode === "dashboard" ? "layout-report.json" : `${mode}-report.json`;
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
const report = { mode, url, checkedAt: new Date().toISOString(), viewports: [] };
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

  const viewports = [
    { name: "target", width: 1214, height: 2159 },
    { name: "narrow", width: 390, height: 844 },
    { name: "compact", width: 320, height: 740 },
    ...(mode === "dashboard" ? [{ name: "api-offline", width: 1214, height: 2159, offline: true }] : []),
    ...(mode === "ticker" ? [{ name: "reduced-motion", width: 390, height: 844, reducedMotion: true }] : []),
  ];
  for (const viewport of viewports) {
    runtimeErrors.length = 0;
    await command("Emulation.setDeviceMetricsOverride", { width: viewport.width, height: viewport.height, deviceScaleFactor: 1, mobile: false });
    await command("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: viewport.reducedMotion ? "reduce" : "no-preference" }] });
    if (viewport.offline) {
      if (!fetchUrls.size) throw new Error("No API request observed for the offline check.");
      await command("Network.setBlockedURLs", { urls: [...fetchUrls] });
    }
    const previousTimeOrigin = await evaluate("performance.timeOrigin");
    const navigation = await command("Page.navigate", { url });
    if (navigation.errorText) throw new Error(navigation.errorText);
    const readyExpression = mode === "ticker" ? "document.querySelector('[data-ticker-preview]')" : mode !== "primitives" ? "document.querySelector('[data-dashboard-root]') && document.querySelector('[data-dashboard-root]').dataset.apiState !== 'loading'" : "document.querySelector('[data-ui-preview]')";
    await waitFor(() => evaluate(`Boolean(performance.timeOrigin !== ${previousTimeOrigin} && document.readyState === 'complete' && (${readyExpression}))`), "the new page ready state");
    await evaluate("document.fonts.ready.then(() => true)");
    await delay(150);
    const inspect = mode === "ticker" ? inspectTickerPreview : mode !== "primitives" ? inspectLayout : inspectPrimitives;
    const measurements = await evaluate(`(${inspect.toString()})()`);
    const issues = [];
    if (measurements.viewportWidth !== viewport.width || measurements.viewportHeight !== viewport.height) issues.push("Unexpected CSS viewport");
    if (measurements.documentWidth > measurements.layoutWidth) issues.push("Document has horizontal overflow");
    if (measurements.clippedHeadings) issues.push("Heading text is clipped");
    if (measurements.layoutShiftScore > 0.01) issues.push("Unexpected initial layout shift");
    if (runtimeErrors.length) issues.push("Browser JavaScript exceptions");
    if (mode === "ticker") {
      if (!measurements.fixtureBanner || measurements.quoteCount !== 3 || measurements.tickerHeight !== 47) issues.push("Incomplete/stretched ticker preview");
      measurements.interactions = await inspectTickerInteractions(command, evaluate, async (name) => {
        const capture = await command("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
        await writeFile(join(output, `${viewport.name}-${name}.png`), Buffer.from(capture.data, "base64"));
      });
      if (Object.values(measurements.interactions).some((passed) => passed !== true)) issues.push("Ticker interaction/state check failed");
      if (fetchUrls.size) issues.push("Ticker preview must not request market data");
    } else if (mode === "primitives") {
      if (!measurements.fixtureBanner || measurements.summaryCount !== 6 || measurements.stateCount !== 6 || !measurements.nonNseVisible) issues.push("Incomplete labeled component preview");
      if (measurements.invalidSvg || measurements.clippedSvgText) issues.push("Invalid/clipped SVG geometry or labels");
      const interactions = await inspectTooltip(command, evaluate);
      measurements.interactions = interactions;
      if (!interactions.hover || !interactions.focusZero || !interactions.escape) issues.push("Tooltip pointer/keyboard check failed");
      await evaluate("document.activeElement?.blur(); window.scrollTo(0, 0)");
    } else {
      if (measurements.panels.length !== 6) issues.push("Expected six indicator regions");
      if (measurements.panels.map((panel) => panel.id).join(",") !== "gdp_growth,debt_to_gdp,trade,gst_collection,inflation_india,government_expenditure") issues.push("Panel order differs from reference");
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
      if (mode === "panels") {
        const panels = await evaluate(`(${inspectPanels.toString()})()`);
        Object.assign(measurements, panels);
        if (!panels.fixtureBanner || panels.summaryCount !== 12 || panels.iconCount !== 12 || panels.chartCount !== 6) issues.push("Incomplete labeled panel preview");
        if (panels.plotKinds.join(",") !== "gdp,debt,trade,gst,inflation,expenditure") issues.push("Missing specialized plot types");
        if (panels.invalidSvg || panels.clippedSvgText) issues.push("Invalid/clipped panel SVG geometry or text");
        measurements.interactions = await inspectPanelTooltips(command, evaluate);
        if (measurements.interactions.some((entry) => !entry.hover || !entry.focus || !entry.escape)) issues.push("Panel tooltip interaction failed");
        measurements.sourceLink = await inspectSourceLink(command, evaluate, "[data-panel-id] .source-as-of a");
        if (!measurements.sourceLink) issues.push("Source link keyboard activation failed");
        await evaluate("document.activeElement?.blur(); window.scrollTo(0, 0)");
      }
      if (mode === "states") {
        measurements.states = await inspectStates(command, evaluate, async (name) => {
          const capture = await command("Page.captureScreenshot", { format: "png", clip: { x: 0, y: 0, width: viewport.width, height: viewport.height, scale: 1 }, captureBeyondViewport: true });
          await writeFile(join(output, `${viewport.name}-${name}.png`), Buffer.from(capture.data, "base64"));
        });
        if (Object.values(measurements.states).some((passed) => passed !== true)) issues.push("State/retention/metadata check failed");
        if (fetchUrls.size) issues.push("Synthetic states must use the injected transport only");
      }
    }
    if (["dashboard", "panels", "states"].includes(mode)) {
      measurements.skipLink = await inspectSkipLink(command, evaluate, "#dashboard-main");
      if (!measurements.skipLink) issues.push("Skip link keyboard activation failed");
      await evaluate("document.activeElement?.blur(); window.scrollTo(0, 0)");
    }
    if (runtimeErrors.length && !issues.includes("Browser JavaScript exceptions")) issues.push("Browser JavaScript exceptions");
    const screenshot = await command("Page.captureScreenshot", {
      format: "png", clip: { x: 0, y: 0, width: viewport.width, height: viewport.height, scale: 1 }, captureBeyondViewport: true,
    });
    await writeFile(join(output, `${viewport.name}.png`), Buffer.from(screenshot.data, "base64"));
    if (mode === "panels" && viewport.name === "narrow") {
      const height = await evaluate("document.documentElement.scrollHeight");
      const full = await command("Page.captureScreenshot", { format: "png", clip: { x: 0, y: 0, width: viewport.width, height, scale: 1 }, captureBeyondViewport: true });
      await writeFile(join(output, "narrow-full.png"), Buffer.from(full.data, "base64"));
    }
    if (mode === "panels" && viewport.name === "target") {
      for (const panel of measurements.panels) {
        const capture = await command("Page.captureScreenshot", { format: "png", clip: { x: panel.x, y: panel.y, width: panel.width, height: panel.height, scale: 1 }, captureBeyondViewport: true });
        await writeFile(join(output, `${panel.id}.png`), Buffer.from(capture.data, "base64"));
      }
    }
    report.viewports.push({ ...viewport, ...measurements, runtimeErrors: [...runtimeErrors], issues });
    console.log(`${issues.length ? "FAIL" : "PASS"} ${viewport.name} ${viewport.width}x${viewport.height}: overflow=${Math.max(0, measurements.documentWidth - measurements.layoutWidth)}px, layoutShift=${measurements.layoutShiftScore}`);
  }
  report.fetchUrls = [...fetchUrls];
  await writeFile(join(output, reportName), `${JSON.stringify(report, null, 2)}\n`);
  if (report.viewports.some((entry) => entry.issues.length)) throw new Error(`Layout checks failed. See ${join(output, reportName)}`);
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

function inspectPrimitives() {
  const svg = document.querySelector(".chart-frame svg");
  return {
    viewportWidth: innerWidth, viewportHeight: innerHeight,
    layoutWidth: document.documentElement.clientWidth,
    documentWidth: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
    layoutShiftScore: window.layoutShiftScore,
    clippedHeadings: [...document.querySelectorAll(".ui-preview h1, .ui-preview h2")].some((heading) => heading.scrollWidth > heading.clientWidth + 1 || heading.scrollHeight > heading.clientHeight + 1),
    fixtureBanner: document.querySelector("[data-fixture-banner]").textContent.includes("Synthetic data, not financial observations"),
    summaryCount: document.querySelectorAll(".summary-value").length,
    stateCount: document.querySelectorAll(".preview-states [data-state]").length,
    nonNseVisible: Boolean(document.querySelector(".source-tag")),
    invalidSvg: [...svg.querySelectorAll("*")].some((node) => [...node.attributes].some((attribute) => /NaN|Infinity/.test(attribute.value))),
    clippedSvgText: [...svg.querySelectorAll("text")].some((node) => {
      const box = node.getBBox();
      return box.x < -1 || box.y < -1 || box.x + box.width > svg.viewBox.baseVal.width + 1 || box.y + box.height > svg.viewBox.baseVal.height + 1;
    }),
  };
}

async function inspectTooltip(command, evaluate) {
  const coordinates = await evaluate(`(() => {
    const point = document.querySelector('.chart-point');
    point.scrollIntoView({ block: 'center' });
    const box = point.getBoundingClientRect();
    return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
  })()`);
  await command("Input.dispatchMouseEvent", { type: "mouseMoved", ...coordinates });
  await delay(50);
  const hover = await evaluate("Boolean(document.querySelector('[role=tooltip]')?.textContent.includes('Example A'))");
  await command("Input.dispatchMouseEvent", { type: "mouseMoved", x: 0, y: 0 });
  await evaluate("document.querySelectorAll('.chart-point')[1].focus()");
  await delay(50);
  const focusZero = await evaluate("Boolean(document.querySelector('[role=tooltip]')?.textContent.includes('Real zero') && document.querySelector('[role=tooltip]')?.textContent.includes('0.00%'))");
  await command("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape" });
  await command("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape" });
  await delay(50);
  const escape = await evaluate("!document.querySelector('[role=tooltip]')");
  return { hover, focusZero, escape };
}

function inspectPanels() {
  const charts = [...document.querySelectorAll(".indicator-chart svg")];
  return {
    fixtureBanner: document.querySelector("[data-fixture-banner]")?.textContent.includes("Not financial observations"),
    summaryCount: document.querySelectorAll(".panel-summaries .summary-value").length,
    iconCount: document.querySelectorAll(".panel-icon").length,
    chartCount: charts.length,
    plotKinds: [...document.querySelectorAll("[data-plot-kind]")].map((node) => node.dataset.plotKind),
    invalidSvg: charts.some((svg) => [...svg.querySelectorAll("*")].some((node) => [...node.attributes].some((attribute) => /NaN|Infinity/.test(attribute.value)))),
    clippedSvgText: charts.some((svg) => [...svg.querySelectorAll("text")].some((node) => {
      const box = node.getBBox();
      return box.x < -1 || box.y < -1 || box.x + box.width > svg.viewBox.baseVal.width + 1 || box.y + box.height > svg.viewBox.baseVal.height + 1;
    })),
  };
}

async function inspectPanelTooltips(command, evaluate) {
  const checks = [];
  for (let index = 0; index < 6; index++) {
    const coordinates = await evaluate(`(() => {
      const point = document.querySelectorAll('[data-panel-id]')[${index}].querySelector('.chart-point');
      point.scrollIntoView({ block: 'center' });
      const bounds = (point.querySelector(':scope > rect, :scope > circle') ?? point).getBoundingClientRect();
      return { x: bounds.x + bounds.width / 2, y: bounds.y + bounds.height / 2 };
    })()`);
    await command("Input.dispatchMouseEvent", { type: "mouseMoved", ...coordinates });
    await delay(40);
    const hover = await evaluate(`Boolean(document.querySelectorAll('[data-panel-id]')[${index}].querySelector('[role=tooltip]'))`);
    await command("Input.dispatchMouseEvent", { type: "mouseMoved", x: 0, y: 0 });
    await evaluate(`document.querySelectorAll('[data-panel-id]')[${index}].querySelector('.chart-point').focus()`);
    await delay(40);
    const focus = await evaluate(`Boolean(document.querySelectorAll('[data-panel-id]')[${index}].querySelector('[role=tooltip]'))`);
    await command("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape" });
    await command("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape" });
    await delay(40);
    const escape = await evaluate("!document.querySelector('[role=tooltip]')");
    checks.push({ panel: index, hover, focus, escape });
  }
  return checks;
}

async function keyPress(command, key, code = key, extra = {}) {
  const windowsVirtualKeyCode = { Enter: 13, Tab: 9, Escape: 27, " ": 32, End: 35, Home: 36, ArrowLeft: 37, ArrowRight: 39 }[key];
  const text = key === "Enter" ? "\r" : key === " " ? " " : undefined;
  await command("Input.dispatchKeyEvent", { type: "keyDown", key, code, windowsVirtualKeyCode, text, ...extra });
  await command("Input.dispatchKeyEvent", { type: "keyUp", key, code, windowsVirtualKeyCode, ...extra });
  await delay(35);
}

async function inspectSkipLink(command, evaluate, target) {
  await evaluate("document.activeElement?.blur(); window.scrollTo(0, 0); document.querySelector('.skip-link').focus()");
  await keyPress(command, "Tab");
  await keyPress(command, "Tab", "Tab", { modifiers: 8 });
  await evaluate("window.scrollTo(0, 0)");
  const focus = await evaluate("document.activeElement.matches(':focus-visible') && document.activeElement.getBoundingClientRect().y >= 0");
  await keyPress(command, "Enter");
  const activated = await evaluate(`document.activeElement === document.querySelector(${JSON.stringify(target)})`);
  return focus && activated;
}

async function inspectSourceLink(command, evaluate, selector) {
  // Exercise native keyboard activation while preventing navigation to fixture URLs.
  const ready = await evaluate(`(() => {
    const link = document.querySelector(${JSON.stringify(selector)});
    if (!link) return false;
    window.activatedSource = null;
    link.addEventListener('click', (event) => { event.preventDefault(); window.activatedSource = link.href; }, { once: true });
    link.focus();
    return link.href.startsWith('https://example.com/') && link.target === '_blank' && link.rel.includes('noopener') && link.rel.includes('noreferrer');
  })()`);
  await keyPress(command, "Enter");
  return ready && await evaluate("Boolean(window.activatedSource?.startsWith('https://example.com/'))");
}

function inspectTickerPreview() {
  return {
    viewportWidth: innerWidth, viewportHeight: innerHeight,
    layoutWidth: document.documentElement.clientWidth,
    documentWidth: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
    layoutShiftScore: window.layoutShiftScore,
    clippedHeadings: [...document.querySelectorAll('h1, h2')].some((node) => node.scrollWidth > node.clientWidth + 1),
    fixtureBanner: document.querySelector('[data-fixture-banner]')?.textContent.includes('Not financial observations'),
    tickerHeight: document.querySelector('.market-ticker').getBoundingClientRect().height,
    quoteCount: document.querySelectorAll('.ticker-quote').length,
    reducedMotion: matchMedia('(prefers-reduced-motion: reduce)').matches,
  };
}

async function inspectTickerInteractions(command, evaluate, capture) {
  const checks = {};
  const click = async (selector) => {
    const point = await evaluate(`(() => {
      const node = document.querySelector(${JSON.stringify(selector)});
      node.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      const box = node.getBoundingClientRect();
      return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
    })()`);
    await command("Input.dispatchMouseEvent", { type: "mousePressed", button: "left", clickCount: 1, ...point });
    await command("Input.dispatchMouseEvent", { type: "mouseReleased", button: "left", clickCount: 1, ...point });
    await delay(40);
  };
  const scenario = async (name) => {
    if (await evaluate("Boolean(document.querySelector('.ticker-details'))")) await keyPress(command, "Escape");
    await click(`[data-scenario="${name}"]`);
  };
  checks.skipLink = await inspectSkipLink(command, evaluate, "#ticker-preview-main");
  await evaluate("window.scrollTo(0, 0); document.querySelector('.ticker-scroll').focus(); document.querySelector('.ticker-scroll').scrollLeft = 0");
  await keyPress(command, "ArrowRight");
  const overflow = await evaluate("document.querySelector('.ticker-scroll').scrollWidth > document.querySelector('.ticker-scroll').clientWidth");
  checks.rightScroll = await evaluate(`!${overflow} || document.querySelector('.ticker-scroll').scrollLeft > 0`);
  await keyPress(command, "End");
  checks.endScroll = await evaluate("(() => { const s = document.querySelector('.ticker-scroll'); return Math.abs(s.scrollWidth - s.clientWidth - s.scrollLeft) <= 1; })()");
  await keyPress(command, "ArrowLeft");
  checks.leftScroll = await evaluate(`!${overflow} || document.querySelector('.ticker-scroll').scrollLeft < document.querySelector('.ticker-scroll').scrollWidth - document.querySelector('.ticker-scroll').clientWidth`);
  await keyPress(command, "Home");
  checks.homeScroll = await evaluate("document.querySelector('.ticker-scroll').scrollLeft === 0");
  await keyPress(command, "Tab");
  checks.tabFocus = await evaluate("document.activeElement.matches('.ticker-quote:focus-visible') && getComputedStyle(document.activeElement).outlineStyle !== 'none'");
  await keyPress(command, "Enter");
  checks.enterOpen = await evaluate("document.querySelector('.ticker-quote').getAttribute('aria-expanded') === 'true' && Boolean(document.querySelector('.ticker-details'))");
  if (!checks.enterOpen) throw new Error(`Ticker keyboard open failed: ${JSON.stringify(checks)}; active=${await evaluate("document.activeElement.outerHTML")}`);
  checks.metadata = await evaluate("(() => { const d = document.querySelector('.ticker-details'); return d.textContent.includes('Synthetic schedule: every 60 seconds; not tick-by-tick') && d.textContent.includes('2 Jan 2025, 10:30:00 UTC') && d.textContent.includes('Non-NSE') && d.textContent.includes('321.12') && d.querySelector('time')?.dateTime === '2025-01-02T10:30:00Z'; })()");
  checks.detailsBounds = await evaluate("(() => { const d = document.querySelector('.ticker-details'); const b = d.getBoundingClientRect(); return b.x >= 0 && b.right <= document.documentElement.clientWidth && d.scrollWidth <= d.clientWidth + 1; })()");
  await capture("details");
  checks.sourceLink = await inspectSourceLink(command, evaluate, ".ticker-details .source-as-of a");
  await keyPress(command, "Escape");
  checks.escapeReturn = await evaluate("!document.querySelector('.ticker-details') && document.activeElement.matches('.ticker-quote')");
  await keyPress(command, " ", "Space");
  checks.spaceOpen = await evaluate("Boolean(document.querySelector('.ticker-details'))");
  await click(".ticker-close");
  checks.closeReturn = await evaluate("!document.querySelector('.ticker-details') && document.activeElement.matches('.ticker-quote')");
  await keyPress(command, "Enter");
  await evaluate("document.querySelector('[data-scenario=scheduled]').focus()");
  await delay(40);
  checks.focusDismiss = await evaluate("!document.querySelector('.ticker-details')");
  await click(".ticker-quote");
  await click(".dashboard-header");
  checks.outsideDismiss = await evaluate("!document.querySelector('.ticker-details')");
  await click(".ticker-quote");
  await click(".ticker-quote");
  checks.toggleDismiss = await evaluate("!document.querySelector('.ticker-details')");
  await click(".ticker-quote");
  await click("[data-instrument-id=synthetic_bank]");
  checks.selection = await evaluate("document.querySelector('.ticker-details h2').textContent.includes('NIFTY BANK') && document.querySelector('.ticker-details').textContent.includes('-135.60') && document.querySelectorAll('.ticker-quote[aria-expanded=true]').length === 1");
  await keyPress(command, "Escape");
  const stableHeight = await evaluate("document.querySelector('.market-ticker').getBoundingClientRect().height");
  checks.scenarios = true;
  for (const [name, expected] of [["delayed", "DELAYED"], ["updating", "UPDATING"], ["stale", "STALE"], ["partial", "SCHEDULED"], ["loading", "LOADING"], ["error", "ERROR"], ["empty", "NO DATA"], ["unavailable", "NO DATA"]]) {
    await scenario(name);
    const state = await evaluate(`(() => {
      const quotes = [...document.querySelectorAll('.ticker-value')].map((node) => node.textContent);
      const hidden = ['loading', 'error', 'unavailable'].includes(${JSON.stringify(name)});
      return document.querySelector('.market-status').textContent === ${JSON.stringify(expected)} &&
        (!hidden || quotes.every((value) => value === '—')) &&
        (${JSON.stringify(name)} !== 'stale' || document.querySelectorAll('.ticker-stale').length === 3) &&
        (${JSON.stringify(name)} !== 'partial' || quotes[1] === '—' && quotes[2] === '0.00') &&
        (${JSON.stringify(name)} !== 'empty' || document.querySelectorAll('.ticker-quote').length === 0) &&
        document.querySelector('.market-ticker').getBoundingClientRect().height === ${stableHeight};
    })()`);
    checks.scenarios &&= state;
    if (name === "stale") {
      await click(".ticker-quote");
      checks.retention = await evaluate("document.querySelector('.ticker-details').textContent.includes('Stale quote · retained observation')");
      await capture("stale");
    }
    if (name === "partial") {
      await click("[data-instrument-id=synthetic_bank]");
      checks.missingMetadata = await evaluate("(() => { const d = document.querySelector('.ticker-details'); return d.textContent.includes('Quote unavailable') && d.textContent.includes('Source unavailable') && !d.querySelector('time'); })()");
    }
  }
  await scenario("scheduled");
  await click("[data-instrument-id=synthetic_it]");
  checks.zeroDetails = await evaluate("document.querySelector('.ticker-details').textContent.includes('No change: 0.00%')");
  await keyPress(command, "Escape");
  await evaluate("document.activeElement?.blur(); window.scrollTo(0, 0)");
  const initialScroll = await evaluate("document.querySelector('.ticker-scroll').scrollLeft");
  await delay(200);
  checks.manualMotion = await evaluate(`document.querySelector('.ticker-scroll').scrollLeft === ${initialScroll} && !document.getAnimations().some((animation) => animation.playState === 'running') && getComputedStyle(document.querySelector('.ticker-scroll')).scrollBehavior === 'auto'`);
  return checks;
}

async function inspectStates(command, evaluate, capture) {
  const checks = {};
  const select = async (name) => {
    await evaluate(`(() => { const s = document.querySelector('.state-preview-control select'); s.value = ${JSON.stringify(name)}; s.dispatchEvent(new Event('change', { bubbles: true })); })()`);
    await delay(100);
    const expected = ["error", "malformed", "unauthorized"].includes(name) ? "error" : name === "loading" ? "loading" : "ready";
    let ready = false;
    for (let retry = 0; retry < 80; retry++) {
      ready = await evaluate(`document.querySelector('[data-states-preview]').dataset.scenario === ${JSON.stringify(name)} && document.querySelector('[data-states-preview]').dataset.viewPhase === ${JSON.stringify(expected)}`);
      if (ready) break;
      await delay(25);
    }
    if (!ready) throw new Error(`State preview did not settle: ${name}`);
    await evaluate("window.scrollTo(0, 0)");
  };
  const baseline = await evaluate("[...document.querySelectorAll('[data-panel-id]')].map((p) => p.getBoundingClientRect().height)");
  for (const name of ["fresh", "loading", "partial", "empty", "unavailable", "error", "retained", "no-retention", "mixed-retention", "malformed", "unauthorized"]) {
    await select(name);
    const result = await evaluate(`(() => {
      const name = ${JSON.stringify(name)};
      const panels = [...document.querySelectorAll('[data-panel-id]')];
      const values = [...document.querySelectorAll('.panel-summaries .summary-number')].map((n) => n.textContent);
      const nulls = ['loading','empty','unavailable','error','no-retention','malformed','unauthorized'].includes(name);
      let correct = values.length === 12 && (!nulls || values.every((v) => v === '—'));
      if (name === 'fresh') correct &&= values[0] === '7.10%' && values[1] === '3.40%' && values[3] === '—';
      if (name === 'partial') correct &&= values[0] === '7.10%' && values[1] === '—' && values[4] !== '—';
      if (name === 'retained') correct &&= values[0] === '7.10%' && document.querySelectorAll('.summary-state.state-stale').length === 11 && document.querySelector('.market-status').textContent === 'STALE';
      if (name === 'mixed-retention') correct &&= values[0] === '7.10%' && values[1] === '—' && document.querySelector('.market-status').textContent === 'ERROR' && document.querySelector('[data-panel-id=gdp_growth] .chart-frame tbody tr:nth-child(2) td')?.textContent === '—';
      if (['loading','empty','unavailable','error'].includes(name)) correct &&= document.querySelectorAll('.panel-plot-region [data-state=' + name + ']').length === 6;
      if (name === 'malformed') correct &&= document.querySelector('main [role=alert]').textContent.includes('validate');
      if (name === 'unauthorized') correct &&= document.querySelector('main [role=alert]').textContent.includes('Sign in');
      const bounds = panels.every((panel) => panel.getBoundingClientRect().right <= document.documentElement.clientWidth && panel.scrollWidth <= panel.clientWidth + 1);
      const stable = panels.every((panel, i) => Math.abs(panel.getBoundingClientRect().height - ${JSON.stringify(baseline)}[i]) < 1);
      return { correct, bounds, stable, heights: panels.map((p) => p.getBoundingClientRect().height) };
    })()`);
    checks[name] = result.correct && result.bounds && result.stable;
    if (!checks[name]) console.error("State diagnostic", name, result);
    await capture(name);
  }
  await select("fresh");
  await evaluate("document.querySelector('.panel-data-details summary').focus()");
  await keyPress(command, "Enter");
  checks.metadata = await evaluate("(() => { const d = document.querySelector('.panel-data-details'); const p = d.querySelector('.panel-data-popover'); const b = p.getBoundingClientRect(); return d.open && d.textContent.includes('Synthetic API examples') && d.textContent.includes('History: fresh') && b.x >= 0 && b.right <= document.documentElement.clientWidth && p.scrollWidth <= p.clientWidth + 1; })()");
  await capture("series-details");
  checks.metadataLink = await inspectSourceLink(command, evaluate, ".panel-data-popover .source-as-of a");
  await keyPress(command, "Escape");
  checks.metadataEscape = await evaluate("!document.querySelector('.panel-data-details').open && document.activeElement.matches('.panel-data-details summary')");
  await evaluate("document.activeElement?.blur(); window.scrollTo(0, 0)");
  return checks;
}
