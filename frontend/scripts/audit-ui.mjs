// Local, scoped review checks; not a replacement for a full accessibility audit.
export function contrastRatio(foreground, background) {
  const luminance = (hex) => {
    const rgb = hex.replace('#', '').match(/.{2}/g).map((value) => parseInt(value, 16) / 255).map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
    return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
  };
  const [first, second] = [luminance(foreground), luminance(background)];
  return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
}

export function inspectAuditDocument() {
  const ids = [...document.querySelectorAll('[id]')].map((node) => node.id);
  const references = [...document.querySelectorAll('[aria-labelledby], [aria-describedby], [aria-controls]')].flatMap((node) => ['aria-labelledby','aria-describedby','aria-controls'].flatMap((name) => (node.getAttribute(name) ?? '').split(/\s+/).filter(Boolean)));
  const all = [...document.querySelectorAll('*')];
  const hex = (color) => { const rgb = color.match(/[\d.]+/g); return rgb?.length === 3 ? '#' + rgb.map((value) => Math.round(Number(value)).toString(16).padStart(2,'0')).join('') : null; };
  const pairs = [...document.querySelectorAll('.plot-annotation')].filter((node) => node.querySelector('rect')).map((node) => ({ foreground:hex(getComputedStyle(node.querySelector('text')).fill), background:hex(getComputedStyle(node.querySelector('rect')).fill) }));
  return {
    viewportWidth: innerWidth, viewportHeight: innerHeight, layoutWidth: document.documentElement.clientWidth,
    documentWidth: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
    layoutShiftScore: window.layoutShiftScore,
    clippedHeadings: [...document.querySelectorAll('h1,h2')].some((node) => node.scrollWidth > node.clientWidth + 1),
    duplicateIds: ids.length - new Set(ids).size, danglingAria: references.filter((id) => !document.getElementById(id)),
    language: document.documentElement.lang, mainCount: document.querySelectorAll('main').length,
    h1Count: document.querySelectorAll('h1').length, panelCount: document.querySelectorAll('[data-panel-id]').length,
    chartCount: document.querySelectorAll('.chart-frame svg').length,
    dataTableCount: document.querySelectorAll('.chart-frame table').length,
    chartTabStops: document.querySelectorAll('.chart-point[tabindex="0"]').length,
    chartPoints: document.querySelectorAll('.chart-point').length,
    annotationPairs: [...new Map(pairs.map((pair) => [JSON.stringify(pair),pair])).values()],
    barStrokes: [...new Set([...document.querySelectorAll('.plot-bar')].map((node) => hex(getComputedStyle(node).stroke)))],
    statusRegions: document.querySelectorAll('[role=status], [role=alert]').length,
    domNodes: all.length,
    fontStatus: document.fonts.status,
    externalFonts: performance.getEntriesByType('resource').filter((entry) => /\.(woff2?|ttf)(\?|$)/.test(entry.name)).length,
    panels: [...document.querySelectorAll('[data-panel-id]')].map((panel) => {
      const b = panel.getBoundingClientRect(); return {id: panel.dataset.panelId, x: b.x, y: b.y, width: b.width, height: b.height};
    }),
    minChartTextPx: Math.min(...[...document.querySelectorAll('.chart-axes text')].map((node) => parseFloat(getComputedStyle(node).fontSize) * node.ownerSVGElement.getBoundingClientRect().width / node.ownerSVGElement.viewBox.baseVal.width)),
    performance: {
      paints: performance.getEntriesByType('paint').map((entry) => ({name:entry.name,ms:entry.startTime})),
      lcp: window.auditLcp ?? null,
      longTasks: window.auditLongTasks ?? [],
      resources: performance.getEntriesByType('resource').filter((entry) => ['script','link','css'].includes(entry.initiatorType)).map((entry) => ({name:new URL(entry.name).pathname,decodedBytes:entry.decodedBodySize,ms:entry.duration})),
    },
  };
}

export async function auditInteractions(command, evaluate, keyPress) {
  const checks = {};
  await evaluate("document.querySelector('.chart-point').focus()");
  await keyPress(command, 'ArrowRight');
  checks.arrowNavigation = await evaluate("document.activeElement === document.querySelectorAll('.chart-point')[1]");
  await keyPress(command, 'End');
  checks.endNavigation = await evaluate("(() => { const points = document.querySelector('.chart-frame').querySelectorAll('.chart-point'); return document.activeElement === points[points.length - 1]; })()");
  await keyPress(command, 'Home');
  checks.homeNavigation = await evaluate("document.activeElement === document.querySelector('.chart-point')");
  checks.focusRing = await evaluate("getComputedStyle(document.activeElement.querySelector('.chart-focus-ring')).display !== 'none'");
  await keyPress(command, 'Escape');
  checks.escape = await evaluate("!document.querySelector('[role=tooltip]')");
  await keyPress(command, 'Tab');
  checks.singleChartTabStop = await evaluate("!document.activeElement.matches('.chart-point') && document.querySelectorAll('.chart-point[tabindex=\"0\"]').length === 6");
  await evaluate("document.querySelector('.panel-data-details summary').focus()");
  await keyPress(command,'Enter');
  checks.visibleTable = await evaluate("(() => { const details = document.querySelector('.panel-data-details'); const table = details.querySelector('table'); return details.open && table.getBoundingClientRect().height > 0 && parseFloat(getComputedStyle(table).fontSize) >= 14 && table.textContent.includes('8.10%') && table.scrollWidth <= details.querySelector('.panel-data-popover').clientWidth; })()");
  await evaluate("document.querySelector('.panel-data-popover').focus()");
  await keyPress(command,'PageDown');
  checks.tableKeyboardScroll = await evaluate("document.activeElement.matches('.panel-data-popover') && document.activeElement.scrollTop > 0");
  await keyPress(command,'Escape');
  checks.detailsFocusReturn = await evaluate("!document.querySelector('.panel-data-details').open && document.activeElement.matches('.panel-data-details summary')");
  const start = await evaluate("performance.now()");
  await evaluate("(() => { const s = document.querySelector('.state-preview-control select'); s.value = 'dense'; s.dispatchEvent(new Event('change',{bubbles:true})); })()");
  for (let retry=0;retry<100;retry++) {
    if (await evaluate("document.querySelector('[data-panel-id=gdp_growth]').querySelectorAll('.chart-point').length === 1000")) break;
    await new Promise((resolve)=>setTimeout(resolve,30));
  }
  const dense = await evaluate(`({elapsedMs:performance.now()-${start},pointCount:document.querySelector('[data-panel-id=gdp_growth]').querySelectorAll('.chart-point').length,tabStops:document.querySelectorAll('.chart-point[tabindex="0"]').length,axisLabels:document.querySelector('[data-panel-id=gdp_growth]').querySelectorAll('.chart-axes text').length,tableRows:document.querySelector('[data-panel-id=gdp_growth] .chart-frame tbody').rows.length})`);
  await evaluate("document.querySelector('.chart-point').focus()");
  await keyPress(command,'End');
  checks.denseHistory = dense.pointCount === 1000 && dense.tabStops === 6 && dense.axisLabels < 15 && dense.tableRows === 1000 && await evaluate("document.activeElement.getAttribute('aria-label').includes('1999') && Boolean(document.querySelector('[role=tooltip]'))");
  await evaluate("(() => { const s=document.querySelector('.state-preview-control select');s.value='fresh';s.dispatchEvent(new Event('change',{bubbles:true})); })()");
  for (let retry=0;retry<100;retry++) { if (await evaluate("document.querySelector('[data-panel-id=gdp_growth]').querySelectorAll('.chart-point').length === 10 && document.querySelector('[data-states-preview]').dataset.viewPhase === 'ready'")) break; await new Promise((resolve)=>setTimeout(resolve,30)); }
  await evaluate("document.activeElement?.blur(); window.scrollTo(0,0)");
  return {checks,dense};
}
