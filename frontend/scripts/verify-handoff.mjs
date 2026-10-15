import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { build, createServer } from "vite";
import react from "@vitejs/plugin-react";

const root = fileURLToPath(new URL('../', import.meta.url));
if (process.argv.length > 2 && (process.argv[2] !== '--output' || process.argv.length !== 4)) throw new Error('Use --output <report.json>.');
const output = process.argv[3] ? resolve(process.argv[3]) : join(root,'node_modules/.cache/handoff/handoff-report.json');
const productionModules = new Set();
const result = await build({root,logLevel:'error',build:{write:false},plugins:[{
  name:'verify-handoff-module-graph',
  generateBundle(_options,bundle) {
    for (const chunk of Object.values(bundle)) if (chunk.type === 'chunk') for (const id of Object.keys(chunk.modules)) productionModules.add(id.replaceAll('\\','/'));
  },
}]});
const chunks = (Array.isArray(result) ? result : [result]).flatMap((entry)=>entry.output).filter((entry)=>entry.type === 'chunk');
assert.ok(productionModules.size > 0,'Production module graph must be available.');
assert.ok([...productionModules].some((id)=>id.endsWith('/components/DashboardScreen.tsx')));
assert.ok(![...productionModules].some((id)=>id.includes('/src/preview/')),'Preview module in production graph.');
for (const marker of ['__ui-preview','__panel-preview','__ticker-preview','__states-preview','synthetic_snapshot_1','synthetic-preview-token','synthetic_gst_average_growth']) assert.ok(!chunks.some((chunk)=>chunk.code.includes(marker)),`Development marker in production: ${marker}`);
console.log('PASS production graph: no preview modules/routes or fixture markers');

const server = await createServer({root,configFile:false,cacheDir:'node_modules/.cache/handoff/vite',plugins:[react()],server:{middlewareMode:true,hmr:false},appType:'custom'});
try {
  const {loadDashboard}=await server.ssrLoadModule('/src/data/dashboard-client.ts');
  const {beginRefresh}=await server.ssrLoadModule('/src/data/dashboard-state.ts');
  const {panelBindings}=await server.ssrLoadModule('/src/data/dashboard-contract.ts');
  const {apiBaseUrl}=await server.ssrLoadModule('/src/config.ts');
  const {default:Screen}=await server.ssrLoadModule('/src/components/DashboardScreen.tsx');
  const {dashboardFixture,responseFixture,stateScenarioNames}=await server.ssrLoadModule('/src/preview/dashboard-fixtures.ts');
  const signal=new AbortController().signal;
  const request=(payload)=>async(url,options)=>{
    assert.equal(url,`${apiBaseUrl}/api/v1/dashboard`);
    assert.equal(options.headers.Authorization,'Bearer synthetic-handoff-token');
    assert.equal(options.credentials,'omit');
    return new Response(JSON.stringify(payload));
  };
  const render=(view)=>renderToStaticMarkup(createElement(Screen,{view}));
  const fresh=await loadDashboard(null,signal,'synthetic-handoff-token',request(dashboardFixture()));
  const html=render(fresh);
  const ids=Object.keys(panelBindings);
  assert.equal(ids.length,6);
  assert.equal((html.match(/data-panel-id=/g)??[]).length,6);
  assert.equal((html.match(/class="summary-value"/g)??[]).length,12);
  for(const id of ids) assert.ok(html.includes(`data-panel-id="${id}"`));
  assert.ok(html.includes('7.10%') && html.includes('SCHEDULED') && html.includes('Synthetic API examples') && html.includes('Non-NSE'));
  assert.equal(beginRefresh(fresh.snapshot).snapshot.ticker.refreshing,true);
  console.log('PASS injected response → client → adapter → six panels/ticker');

  const partial=await loadDashboard(fresh.snapshot,signal,'synthetic-handoff-token',request(responseFixture('partial')));
  assert.equal(partial.snapshot.panels.gdp_growth.summaries[0].value,'7.1');
  assert.equal(partial.snapshot.panels.gdp_growth.summaries[1].value,null);
  const retained=await loadDashboard(fresh.snapshot,signal,'synthetic-handoff-token',async()=>new Response(null,{status:503}));
  assert.ok(render(retained).includes('Stale observation'));
  const denied=await loadDashboard(retained.snapshot,signal,'synthetic-handoff-token',async()=>new Response(null,{status:401}));
  assert.equal(denied.snapshot,null);
  assert.ok(!render(denied).includes('7.10%'));
  assert.ok(render(denied).includes('Sign in is required'));
  console.log('PASS partial data, permitted stale retention and unauthorized clearing');

  const testSource=await readFile(join(root,'scripts/test-ui.mjs'),'utf8');
  const report={status:'handoff-ready; module lock conditional',interfaces:{wire:'src/data/dashboard-response.ts#DashboardResponseV1Draft',validated:'src/data/dashboard-contract.ts#DashboardSnapshot',request:'src/data/dashboard-client.ts#loadDashboard',state:'src/data/dashboard-state.ts#DashboardView',screen:'src/components/DashboardScreen.tsx'},panels:Object.entries(panelBindings).map(([id,binding])=>({id,summaries:binding.summaries,series:binding.series.map(({id,unit})=>({id,unit}))})),testInventory:[...testSource.matchAll(/await test\("([^"]+)"/g)].map((match)=>match[1]),previewScenarios:stateScenarioNames,productionPreviewModules:0,liveEndpointTested:false,open:['M3 source/definition approval','M4 draft wire-field acceptance','M5 token/session lifecycle','M6 authenticated polling and request ordering','exact Figma fidelity and manual screen-reader review']};
  report.interactionChecks=['skip link and source-link activation','ticker scroll, quote disclosure, dismissal and focus return','chart pointer inspection, roving focus, Left/Right/Home/End and Escape','series disclosure, history-table keyboard scrolling and focus return','reduced motion, narrow/wide/reflow layouts and dense histories'];
  report.verificationScripts=['test:ui','verify:handoff','verify:layout','verify:primitives','verify:panels','verify:ticker','verify:states','verify:audit','verify:performance'];
  report.priorEvidence=['../m2-f7/visual-review.html','../m2-f7/after/audit-report.json','../m2-f7/states/states-report.json','../m2-f7/production/performance-report.json'];
  await mkdir(dirname(output),{recursive:true});
  await writeFile(output,JSON.stringify(report,null,2)+'\n');
  console.log(`Handoff report: ${output}`);
} finally {await server.close();}
