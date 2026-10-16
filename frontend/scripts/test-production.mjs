import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { checkRenderEnvironment } from "./check-render-env.mjs";

const valid = { NODE_VERSION:"24.19.0",VITE_API_BASE_URL:"https://economic-api.onrender.com",RENDER_EXTERNAL_URL:"https://economic-web.onrender.com" };
await test("Render build accepts separate public HTTPS origins with pinned Node", () => {
  assert.equal(checkRenderEnvironment(valid,"24.19.0").result,"PASS");
  for(const version of ["22.19.0","24.18.0","25.0.0"]) assert.throws(()=>checkRenderEnvironment({...valid,NODE_VERSION:version},version));
  assert.throws(()=>checkRenderEnvironment(valid,"24.21.0"));
});
await test("Render build rejects local/private, credentialed, placeholder and mis-prefixed API URLs", () => {
  for(const VITE_API_BASE_URL of [undefined,"http://api.onrender.com","https://localhost","https://127.0.0.1","https://[::1]",
    "https://10.0.0.1","https://api.example.invalid","https://api.local","https://user:secret@api.onrender.com",
    "https://api.onrender.com/api/v1","https://api.onrender.com?token=secret","https://api.onrender.com/#secret",
    "https://api.onrender.com:8000","https://bad_name.onrender.com",valid.RENDER_EXTERNAL_URL]) {
    assert.throws(()=>checkRenderEnvironment({...valid,VITE_API_BASE_URL},"24.19.0"));
  }
});
await test("Render build refuses any additional VITE_ variable instead of risking public secret injection", () => {
  for(const key of ["VITE_AUTH_JWT_SIGNING_KEY","VITE_DATABASE_DIRECTORY","VITE_PASSWORD"]) {
    assert.throws(()=>checkRenderEnvironment({...valid,[key]:"private-canary"},"24.19.0"), error=>!error.message.includes("private-canary"));
  }
});
await test("Render build CLI exits before building and never echoes invalid credential values", () => {
  const child=spawnSync(process.execPath,[fileURLToPath(new URL("./check-render-env.mjs",import.meta.url))],{
    env:{...process.env,...valid,NODE_VERSION:process.versions.node,VITE_API_BASE_URL:"https://user:private-canary@api.onrender.com"},encoding:"utf8",windowsHide:true,
  });
  assert.equal(child.status,1);assert.ok(!`${child.stdout}${child.stderr}`.includes("private-canary"));
  assert.match(child.stderr,/configuration invalid/);
});
