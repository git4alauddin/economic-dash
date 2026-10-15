import { execFileSync } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import assert from "node:assert/strict";

const root = fileURLToPath(new URL('../', import.meta.url));
const baseline = '592cfc45fb663ee3085afa68af0b0a3e756f8cb5'; // M2.6, before formatter reuse.
const output = process.argv[2] ? resolve(process.argv[2]) : join(root,'node_modules/.cache/audit/format-benchmark.json');
const cache = join(root,'node_modules/.cache/audit');
await mkdir(cache,{recursive:true});
const before = execFileSync('git',['show',`${baseline}:frontend/src/ui/format.ts`],{cwd:root,encoding:'utf8',windowsHide:true});
await writeFile(join(cache,'format-before.ts'),before);
const server = await createServer({root,configFile:false,cacheDir:'node_modules/.cache/audit/vite',server:{middlewareMode:true,hmr:false},appType:'custom'});
try {
  const old = await server.ssrLoadModule('/node_modules/.cache/audit/format-before.ts');
  const current = await server.ssrLoadModule('/src/ui/format.ts');
  const samples = [['9007199254740993.125','usd_billion',2],['123456.789','inr_crore',2],['0','percent',2],['-1.005','percent',2]];
  for (const args of samples) assert.equal(old.formatValue(...args),current.formatValue(...args));
  const run = (format) => {
    for (let index=0;index<100;index++) format(...samples[index%samples.length]);
    return Array.from({length:5},()=>{const start=performance.now();for(let index=0;index<3000;index++) format(...samples[index%samples.length]);return performance.now()-start;});
  };
  const beforeMs=run(old.formatValue),afterMs=run(current.formatValue),median=(values)=>[...values].sort((a,b)=>a-b)[2];
  const result={baseline,iterationsPerSample:3000,samples:5,beforeMs,afterMs,medianBeforeMs:median(beforeMs),medianAfterMs:median(afterMs),outputsEqual:true,note:'Local Node formatting microbenchmark; not browser INP or deployment performance.'};
  await mkdir(resolve(output,'..'),{recursive:true});
  await writeFile(output,JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify(result,null,2));
} finally {await server.close();}
