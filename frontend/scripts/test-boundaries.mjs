import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { build, createServer } from "vite";
import { privateDataBoundary } from "./private-data-boundary.mjs";

const frontend = fileURLToPath(new URL("../", import.meta.url));
async function workspace(t) {
  const directory = await mkdtemp(join(tmpdir(), "economic-dash-boundary-"));
  t.after(async () => {
    const child = relative(resolve(tmpdir()), resolve(directory));
    assert.ok(child.startsWith("economic-dash-boundary-") && !isAbsolute(child) && !child.startsWith(".."));
    await rm(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  });
  return directory;
}

await test("configured Vite serves the app but refuses env, database and outside-root files", async (t) => {
  const temporary = await workspace(t);
  const privateFile = join(temporary, "private.sqlite3");
  await writeFile(privateFile, "SQLite format 3\0synthetic private canary");
  const server = await createServer({ root: frontend, logLevel: "silent", cacheDir: join(temporary, "cache"),
    server: { host: "127.0.0.1", port: 0, strictPort: true, hmr: false } });
  t.after(() => server.close());
  await server.listen();
  const address = server.httpServer.address();
  const origin = `http://127.0.0.1:${address.port}`;
  assert.equal((await fetch(origin + "/")).status, 200);
  assert.equal((await fetch(origin + "/src/main.tsx")).status, 200);
  for (const file of [join(frontend, ".env.example"), join(frontend, "../backend/.env.example"), privateFile]) {
    const result = await fetch(`${origin}/@fs/${file.replaceAll("\\", "/")}`);
    assert.equal(result.status, 403, "Private/outside-root file was served");
    assert.ok(!(await result.text()).includes("synthetic private canary"));
  }
  assert.equal(server.config.publicDir, "");
});

await test("real production builds reject private imports, database bytes and private key/hash material", async (t) => {
  const temporary = await workspace(t);
  const scenarios = [
    { name: "safe", code: "console.log('public dashboard');", allowed: true },
    { name: "env", code: "import value from './.env.local?raw'; console.log(value);", file: ".env.local", content: "synthetic env canary" },
    { name: "outside", code: "import value from '../server.mjs'; console.log(value);" },
    { name: "sqlite", code: "import value from './payload.bin?url'; console.log(value);", file: "payload.bin", content: "SQLite format 3\0" + "x".repeat(5000) },
    { name: "key", code: "console.log('-----BEGIN PRIVATE KEY-----synthetic canary');" },
    { name: "hash", code: "console.log('$argon2id$v=19$synthetic canary');" },
  ];
  await writeFile(join(temporary, "server.mjs"), "export default 'synthetic backend module';");
  for (const scenario of scenarios) {
    const root = join(temporary, scenario.name);
    await mkdir(root);
    await writeFile(join(root, "index.html"), '<script type="module" src="/main.js"></script>');
    await writeFile(join(root, "main.js"), scenario.code);
    if (scenario.file) await writeFile(join(root, scenario.file), scenario.content);
    const compile = () => build({ root, configFile: false, publicDir: false, logLevel: "silent",
      plugins: [privateDataBoundary(root)], build: { write: false, assetsInlineLimit: 0 } });
    if (scenario.allowed) await compile();
    else await assert.rejects(compile, (error) => {
      assert.ok(error.message.includes("private-data-boundary"), "Build failed outside the boundary guard");
      assert.ok(!error.message.includes("synthetic canary"), "Build error echoed private file content");
      return true;
    }, scenario.name);
  }
});
