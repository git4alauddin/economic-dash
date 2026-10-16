import assert from "node:assert/strict";
import { setTimeout as delay } from "node:timers/promises";

// Isolated test page only. Track live timer handles, not callbacks or credentials.
export const timerAuditScript = `(() => {
  const timeouts=new Map(),intervals=new Map();
  const set=window.setTimeout.bind(window),clear=window.clearTimeout.bind(window);
  const repeat=window.setInterval.bind(window),clearRepeat=window.clearInterval.bind(window);
  window.setTimeout=(fn,ms,...args)=>{
    let id=set(()=>{timeouts.delete(id);typeof fn==='function'?fn(...args):(0,eval)(fn)},ms);
    timeouts.set(id,Number(ms)||0);return id;
  };
  window.clearTimeout=id=>{timeouts.delete(id);intervals.delete(id);clear(id)};
  window.setInterval=(fn,ms,...args)=>{const id=repeat(fn,ms,...args);intervals.set(id,Number(ms)||0);return id};
  window.clearInterval=id=>{timeouts.delete(id);intervals.delete(id);clearRepeat(id)};
  const tasks=[];
  if(PerformanceObserver.supportedEntryTypes.includes('longtask'))
    new PerformanceObserver(list=>{for(const item of list.getEntries())if(tasks.length<500)tasks.push(item.duration)}).observe({type:'longtask',buffered:true});
  window.__reliabilityAudit=()=>({longTimeouts:[...timeouts.values()].filter(ms=>ms>=10000).sort((a,b)=>a-b),
    intervals:intervals.size,longTasks:tasks.length,maxLongTaskMs:Math.max(0,...tasks)});
})()`;

const settle = evaluate => evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))");
const round = value => Math.round(value * 100) / 100;

// Real API responses are delayed, never replaced with plausible synthetic data.
export async function auditReliability({ command, evaluate, click, signIn, dashboard, visible, waitFor,
  requests, timings, indicatorBodies, apiUrl, hold, release, isHeld }) {
  const snapshot = () => evaluate("window.__reliabilityAudit()");
  const dashboardReads = () => requests.filter(item => item.method === "GET" && item.url === `${apiUrl}/api/v1/dashboard`);
  const before = dashboardReads().length;
  await hold();
  const start = performance.now();
  await click("Refresh data");
  await waitFor(isHeld, "delayed real dashboard request");
  await evaluate(`(()=>{const button=Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Updating…');
    for(let i=0;i<50;i++)button?.click();return true})()`);
  await delay(700);
  assert.equal(dashboardReads().length - before, 1, "Slow refresh spawned duplicate dashboard reads");
  assert.ok(await evaluate("!!document.querySelector('[data-dashboard-root]')&&!!document.querySelector('.summary-number')"));
  assert.equal(await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Updating…')?.disabled"), true);
  await release(); await dashboard(); await settle(evaluate);
  const delayedReadMs = round(performance.now() - start);
  assert.equal(dashboardReads().length - before, 1, "Delayed completion triggered an immediate retry");

  await command("Performance.enable");
  const readMetrics = async () => Object.fromEntries((await command("Performance.getMetrics")).metrics.map(item=>[item.name,item.value]));
  const refreshMs = [], renderWork = [];
  for (let sample = 0; sample < 5; sample++) {
    const baseline = await readMetrics();
    const count = dashboardReads().length, start = performance.now();
    await click("Refresh data"); await dashboard(); await settle(evaluate);
    refreshMs.push(round(performance.now() - start));
    const after = await readMetrics();
    renderWork.push(Object.fromEntries(['ScriptDuration','LayoutDuration','RecalcStyleDuration','TaskDuration'].map(key=>[key,round((after[key]-baseline[key])*1000)])));
    assert.equal(dashboardReads().length - count, 1, "One refresh issued multiple dashboard reads");
    assert.equal(dashboardReads().at(-1).conditional, true, "Refresh lost its cache validator");
  }

  await evaluate("document.querySelector('.panel-data-details').open=true;true");
  await visible("!!document.querySelector('.panel-data-details select[aria-label=\"History window\"]')", "history window for bounded render benchmark");
  const beforeHistory=requests.length, beforeBodies=indicatorBodies.length, baseline=await readMetrics(), historyStart=performance.now();
  await evaluate(`(()=>{const node=document.querySelector('.panel-data-details select[aria-label="History window"]');
    node.value='24';node.dispatchEvent(new Event('change',{bubbles:true}));return true})()`);
  await visible("document.querySelector('.panel-data-details [role=status]')?.textContent.startsWith('Selected history.')", "24-period real history rendered");
  await waitFor(()=>indicatorBodies.slice(beforeBodies).some(item=>new URL(item.url).pathname==='/api/v1/indicators/gdp_growth'), "bounded history response capture");
  await settle(evaluate);
  const historyMs=round(performance.now()-historyStart), historyAfter=await readMetrics();
  const body=indicatorBodies.slice(beforeBodies).findLast(item=>new URL(item.url).pathname==='/api/v1/indicators/gdp_growth').body.data;
  const historyRequests=requests.slice(beforeHistory).filter(item=>new URL(item.url).pathname==='/api/v1/indicators/gdp_growth');
  assert.equal(historyRequests.length,1,"One history selection issued duplicate series reads");
  assert.equal(new URL(historyRequests[0].url).searchParams.get('window'),'24');
  const rows=await evaluate("Array.from(document.querySelector('.panel-data-details').querySelectorAll('[data-series-id]')).map(node=>({id:node.dataset.seriesId,rows:node.querySelectorAll('tbody tr').length}))");
  for(const series of rows)assert.equal(series.rows,body.series[series.id].history.points.length,"Rendered history lost observations");
  await evaluate("Array.from(document.querySelectorAll('.panel-data-details button')).find(node=>node.textContent==='Latest view').click();true");

  // Synthetic layout stress only; restore text before source-value assertions.
  for (const width of [1214, 320]) {
    await command("Emulation.setDeviceMetricsOverride", { width, height:2159,deviceScaleFactor:1,mobile:false });
    await evaluate("document.querySelector('.panel-data-details').open=true;true");
    await settle(evaluate);
    const layout = await evaluate(`(()=>{
      const heading=document.querySelector('.panel-heading h2'),source=document.querySelector('.panel-data-popover h3');
      const nodes=[heading,source].filter(Boolean),original=nodes.map(node=>[...node.childNodes]);
      for(const node of nodes)node.textContent='LongTitle'.repeat(27).slice(0,240);
      const fits=document.documentElement.scrollWidth<=innerWidth+1&&nodes.every(node=>node.scrollWidth<=node.clientWidth+1);
      nodes.forEach((node,index)=>node.replaceChildren(...original[index]));return fits;
    })()`);
    assert.equal(layout, true, `240-character unbroken titles overflow at ${width}px`);
  }
  await evaluate("document.querySelector('.panel-data-details').open=false;true");
  await command("Emulation.setDeviceMetricsOverride", { width:1214,height:2159,deviceScaleFactor:1,mobile:false });
  await command("Performance.enable");
  const memory = async () => {
    await settle(evaluate); await command("HeapProfiler.collectGarbage");
    const metrics = Object.fromEntries((await command("Performance.getMetrics")).metrics.map(item => [item.name,item.value]));
    return { heapBytes:metrics.JSHeapUsedSize, ...(await command("Memory.getDOMCounters")) };
  };
  const cycles = [];
  // Warm the same document, then compare post-GC signed-out states over five cycles.
  for (let cycle=0;cycle<5;cycle++) {
    await click("Sign out");
    await visible("!!document.querySelector('#username')&&!document.querySelector('[data-dashboard-root]')", "repeat sign-out clears data");
    const timers = await snapshot();
    assert.deepEqual(timers.longTimeouts, [], "Signed-out session retained request/poll/expiry timer");
    assert.equal(timers.intervals, 0, "Signed-out session retained an interval");
    cycles.push(await memory());
    const count=requests.length;
    await evaluate("window.dispatchEvent(new Event('focus'));document.dispatchEvent(new Event('visibilitychange'));true");
    await settle(evaluate);
    assert.equal(requests.length,count,"Signed-out lifecycle events fetched protected data");
    await signIn(); await dashboard(); await settle(evaluate);
    const login=requests.slice(count).filter(item=>item.url.endsWith('/auth/login'));
    const data=requests.slice(count).filter(item=>item.url.endsWith('/dashboard'));
    assert.equal(login.length,1); assert.equal(data.length,1);
    assert.equal(data[0].conditional,false,"Repeated login reused another session's validator");
    const live=await snapshot();
    assert.equal(live.longTimeouts.length,2,"Signed-in session should own only expiry and next-poll timers");
    assert.equal(live.intervals,0,"Signed-in session accumulated intervals");
  }
  const growth = { heapBytes:cycles.at(-1).heapBytes-cycles[0].heapBytes,
    nodes:cycles.at(-1).nodes-cycles[0].nodes, listeners:cycles.at(-1).jsEventListeners-cycles[0].jsEventListeners };
  // Broad local smoke ceilings; timer assertions above catch even one leaked poller.
  assert.ok(growth.heapBytes<2_000_000 && growth.nodes<100 && growth.listeners<30,
    "Repeated session resources grew beyond smoke ceiling: "+JSON.stringify(growth));
  // Chrome can omit loadingFinished for bodyless 304s; response timing still
  // records receipt of headers. Never invent a transfer size or completion time.
  const completed=[...timings.values()].filter(item=>item.path==='/api/v1/dashboard'&&item.response!==undefined);
  const cached=completed.filter(item=>item.status===304);
  assert.ok(cached.length>=5,"Cached refreshes were not observed in the browser waterfall");
  assert.ok(completed.every(item=>item.start<=item.response),"Response preceded request start");
  const tasks=await snapshot();
  return { localOnly:true, delayedReadMs, slowReadRequests:1, repeatedSessions:5, refreshSamplesMs:refreshMs,
    refreshMedianMs:[...refreshMs].sort((a,b)=>a-b)[2],renderWorkMs:renderWork,
    history24:{requests:1,elapsedMs:historyMs,rows:rows.reduce((sum,item)=>sum+item.rows,0),
      workMs:Object.fromEntries(['ScriptDuration','LayoutDuration','RecalcStyleDuration','TaskDuration'].map(key=>[key,round((historyAfter[key]-baseline[key])*1000)]))},
    waterfall:completed.map(item=>({status:item.status,ttfbMs:round((item.response-item.start)*1000),
      totalMs:item.finish===undefined?null:round((item.finish-item.start)*1000),encodedBytes:item.bytes??null,
      completionEvent:item.finish!==undefined?'finished':item.failed?'body_not_loaded':'not_observed'})),
    signedOutResources:cycles,resourceGrowth:growth,longTasks:tasks.longTasks,maxLongTaskMs:round(tasks.maxLongTaskMs),
    timerCleanupVerified:true,duplicateRefreshes:0,titleStressWidths:[1214,320],
    note:"Local Chrome production build; refresh samples include polling probe/two animation frames. GC smoke is not a heap leak proof or hosted latency/INP." };
}
