import { inspectAuditDocument, contrastRatio } from "./audit-ui.mjs";

const settle = (evaluate) => evaluate("document.fonts.ready.then(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))");
async function waitFor(evaluate, expression) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (await evaluate(expression)) return;
    await new Promise((resolve) => setTimeout(resolve, 30));
  }
  throw Error("Usability interaction did not settle: " + expression);
}
async function key(command, value) {
  const windowsVirtualKeyCode = { Enter:13, Tab:9, Escape:27, PageUp:33, PageDown:34, End:35, Home:36, ArrowRight:39 }[value];
  await command("Input.dispatchKeyEvent", { type: "keyDown", key: value, code: value, windowsVirtualKeyCode, ...(value === "Enter" ? { text: "\r" } : {}) });
  await command("Input.dispatchKeyEvent", { type: "keyUp", key: value, code: value, windowsVirtualKeyCode });
}
async function keyboardAudit(command, evaluate) {
  const checks = {};
  await evaluate("document.querySelector('.skip-link').focus();true");
  await key(command, "Enter");
  checks.skipLink = await evaluate("document.activeElement.id==='dashboard-main'");
  await evaluate("document.querySelector('.chart-point[tabindex=\"0\"]').focus();true");
  await waitFor(evaluate, "!!document.querySelector('[role=tooltip]')");
  await key(command, "End");
  checks.chartEnd = await evaluate("document.activeElement===Array.from(document.activeElement.closest('svg').querySelectorAll('.chart-point')).at(-1)");
  checks.chartFocus = await evaluate("getComputedStyle(document.activeElement.querySelector('.chart-focus-ring')).display!=='none'");
  await key(command, "Home");
  checks.chartHome = await evaluate("document.activeElement===document.activeElement.closest('svg').querySelector('.chart-point')");
  await key(command, "Escape");
  await waitFor(evaluate, "!document.querySelector('[role=tooltip]')");
  await key(command, "Tab");
  checks.chartTabExit = await evaluate("!document.activeElement.matches('.chart-point')");
  await evaluate("document.querySelector('.panel-data-details summary').focus();true");
  await key(command, "Enter");
  await waitFor(evaluate, "!!document.querySelector('.panel-data-details[open] select')");
  await key(command, "Tab");
  await key(command, "Tab");
  checks.namedControlFocus = await evaluate("document.activeElement.tagName==='SELECT'&&!!document.activeElement.getAttribute('aria-label')&&getComputedStyle(document.activeElement).outlineStyle!=='none'");
  checks.controlSize = await evaluate("Array.from(document.querySelectorAll('.panel-data-details[open] select,.panel-data-details[open] button')).every(node=>parseFloat(getComputedStyle(node).fontSize)>=14&&node.getBoundingClientRect().height>=24)");
  await evaluate("document.querySelector('.panel-data-details[open] .panel-data-popover').focus();document.activeElement.scrollIntoView({block:'center'});true");
  // Let native focus/scroll targeting settle before sending a trusted scroll key.
  await settle(evaluate);
  await waitFor(evaluate, "document.activeElement.matches('.panel-data-popover')");
  await key(command, "PageDown");
  try { await waitFor(evaluate, "document.querySelector('.panel-data-details[open] .panel-data-popover').scrollTop>0"); }
  catch {
    throw Error("Native history scroll failed: "+JSON.stringify(await evaluate(`(()=>{const node=document.querySelector('.panel-data-details[open] .panel-data-popover');
      return {width:innerWidth,focused:document.activeElement===node,top:node.scrollTop,height:node.clientHeight,content:node.scrollHeight}})()`)));
  }
  checks.historyScroll = true;
  await key(command, "Home");
  await waitFor(evaluate, "document.querySelector('.panel-data-details[open] .panel-data-popover').scrollTop===0");
  await key(command, "End");
  await waitFor(evaluate, "(()=>{const node=document.querySelector('.panel-data-details[open] .panel-data-popover');return node.scrollTop>=node.scrollHeight-node.clientHeight-1})()");
  await key(command, "PageUp");
  await waitFor(evaluate, "(()=>{const node=document.querySelector('.panel-data-details[open] .panel-data-popover');return node.scrollTop<node.scrollHeight-node.clientHeight-1})()");
  checks.popoverFits = await evaluate("(()=>{const popup=document.querySelector('.panel-data-details[open] .panel-data-popover'),b=popup.getBoundingClientRect();return b.left>=0&&b.right<=document.documentElement.clientWidth+1&&b.top>=0&&b.bottom<=innerHeight+1&&popup.scrollWidth<=popup.clientWidth+1})()");
  await key(command, "Escape");
  checks.detailsFocus = await evaluate("!document.querySelector('.panel-data-details').open&&document.activeElement.matches('.panel-data-details summary')");
  await evaluate("document.querySelector('.ticker-scroll').focus();true");
  await key(command, "End");
  checks.tickerEnd = await evaluate("(()=>{const node=document.querySelector('.ticker-scroll');return node.scrollWidth<=node.clientWidth||node.scrollLeft>0})()");
  await key(command, "Home");
  checks.tickerHome = await evaluate("document.querySelector('.ticker-scroll').scrollLeft===0");
  await evaluate("document.querySelector('.ticker-quote').focus();true");
  await key(command, "Enter");
  await waitFor(evaluate, "!!document.querySelector('.ticker-details')");
  await key(command, "Escape");
  checks.tickerEscape = await evaluate("!document.querySelector('.ticker-details')&&document.activeElement.matches('.ticker-quote')");
  await evaluate("document.activeElement.blur();window.scrollTo(0,0);true");
  return checks;
}

// Production DOM only. Results and optional inspection captures stay in memory.
export async function auditDashboard(command, evaluate, loadingFrames) {
  const views = [];
  for (const viewport of [
    { width: 1214, height: 2159 }, { width: 390, height: 844 }, { width: 320, height: 740 },
    { width: 1920, height: 1080 }, { width: 607, height: 1080 }, { width: 390, height: 844, reduce: true },
  ]) {
    await command("Emulation.setDeviceMetricsOverride", { width: viewport.width, height: viewport.height, deviceScaleFactor: 1, mobile: false });
    await command("Emulation.setPageScaleFactor", { pageScaleFactor: 1 });
    await command("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: viewport.reduce ? "reduce" : "no-preference" }] });
    await settle(evaluate);
    const basic = await evaluate(`(${inspectAuditDocument.toString()})()`);
    const detail = await evaluate(`(() => {
      const root=document.querySelector('[data-dashboard-root]').getBoundingClientRect();
      const rect=node=>{const b=node.getBoundingClientRect();return {x:b.x,y:b.y-root.y,width:b.width,height:b.height}};
      const clipped=Array.from(document.querySelectorAll('.summary-number,.summary-label,.panel-heading h2,.source-as-of')).filter(node=>node.getBoundingClientRect().width>0&&node.scrollWidth>node.clientWidth+1).map(node=>node.className);
      return {rootY:root.y, scale:visualViewport.scale, dpr:devicePixelRatio, header:rect(document.querySelector('.dashboard-header')),ticker:rect(document.querySelector('.market-ticker')),
        panels:Array.from(document.querySelectorAll('[data-panel-id]')).map(node=>({id:node.dataset.panelId,...rect(node)})),clipped,
        headingFont:getComputedStyle(document.querySelector('.panel-heading h2')).fontSize,
        text:getComputedStyle(document.documentElement).color, muted:getComputedStyle(document.documentElement).getPropertyValue('--color-muted').trim(),
        page:getComputedStyle(document.documentElement).backgroundColor,
        minSummaryFont:Math.min(...Array.from(document.querySelectorAll('.summary-number')).map(node=>parseFloat(getComputedStyle(node).fontSize)))};
    })()`);
    const ax = await command("Accessibility.getFullAXTree");
    const unnamed = ax.nodes.filter((node) => !node.ignored && ["button", "combobox", "link", "group"].includes(node.role?.value)
      && !node.name?.value && node.role?.value !== "group").length;
    const issues = [];
    if (basic.viewportWidth !== viewport.width || basic.viewportHeight !== viewport.height || detail.scale !== 1 || detail.dpr !== 1) issues.push("CSS viewport/zoom/scale");
    if (basic.documentWidth > basic.layoutWidth) issues.push("Document overflow");
    if (basic.clippedHeadings || detail.clipped.length) issues.push(`Clipped text: ${detail.clipped.join(",")}`);
    if (basic.duplicateIds || basic.danglingAria.length || basic.mainCount !== 1 || basic.h1Count !== 1 || basic.language !== "en" || unnamed) issues.push("Accessible structure/names");
    if (basic.chartCount !== basic.dataTableCount || basic.chartCount !== basic.chartTabStops || basic.minChartTextPx < 9.99) issues.push("Chart alternatives, focus or text size");
    if (new Set(detail.panels.map((panel) => Math.round(panel.x))).size !== (viewport.width <= 800 ? 1 : 2)) issues.push("Responsive columns");
    if (viewport.width === 1214) for (const [index, panel] of detail.panels.entries()) {
      if (Math.abs(panel.x - (index % 2 ? 619 : 29)) > 4 || Math.abs(panel.y - [158,158,710,710,1263,1263][index]) > 4
        || Math.abs(panel.width - 566.5) > 4 || Math.abs(panel.height - 529) > 4) issues.push(`Reference geometry: ${panel.id}`);
      if (panel.y + detail.rootY + panel.height > viewport.height) issues.push(`Panel below target: ${panel.id}`);
    }
    for (const pair of basic.annotationPairs) if (!pair.foreground || !pair.background || contrastRatio(pair.foreground, pair.background) < 4.5) issues.push("Annotation contrast");
    if (contrastRatio(detail.muted, "#145169") < 4.5) issues.push("Muted text contrast over panel highlight");
    const loading = loadingFrames.find((frame) => frame.width === viewport.width && frame.phase !== "error");
    const loadingDelta = loading ? Math.max(...detail.panels.flatMap((panel, index) => {
      const old = loading.panels[index];
      return [Math.abs(panel.x-old.x),Math.abs(panel.y+detail.rootY-old.y),Math.abs(panel.width-old.width),Math.abs(panel.height-old.height)];
    })) : null;
    if (loadingDelta !== null && loadingDelta > 1) issues.push("Loading layout movement");
    const error = loadingFrames.find((frame) => frame.width === viewport.width && frame.phase === "error");
    const errorDelta = error ? Math.max(...detail.panels.flatMap((panel, index) => {
      const old = error.panels[index];
      return [Math.abs(panel.x-old.x),Math.abs(panel.y+detail.rootY-old.y),Math.abs(panel.width-old.width),Math.abs(panel.height-old.height)];
    })) : null;
    if (errorDelta !== null && errorDelta > 1) issues.push("Initial error layout movement");
    const keyboard = await keyboardAudit(command, evaluate);
    if (Object.values(keyboard).some((passed) => !passed)) issues.push("Keyboard/control usability");
    views.push({ ...viewport, ...detail, chartCount: basic.chartCount, axisFloor: basic.minChartTextPx, unnamed, loadingDelta, errorDelta, keyboard, issues });
  }
  await command("Emulation.setDeviceMetricsOverride", { width: 1214, height: 2159, deviceScaleFactor: 1, mobile: false });
  await command("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "no-preference" }] });
  await evaluate("window.scrollTo(0,0);true");
  return { views };
}
