import { isIP } from "node:net";
import { pathToFileURL } from "node:url";

export function checkRenderEnvironment(env = process.env, version = process.versions.node) {
  if (!env.NODE_VERSION || version !== env.NODE_VERSION) throw Error("Render Node runtime does not match NODE_VERSION.");
  const [major, minor] = version.split(".").map(Number);
  if (major !== 24 || minor < 19) throw Error("Render requires the repository's supported Node 24 runtime.");
  if (Object.keys(env).some(key => key.startsWith("VITE_") && key !== "VITE_API_BASE_URL")) {
    throw Error("Only VITE_API_BASE_URL is allowed as public Render build configuration.");
  }
  let url;
  try { url = new URL(env.VITE_API_BASE_URL); } catch { throw Error("Set the actual HTTPS API origin in Render."); }
  const host = url.hostname.toLowerCase();
  if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash || url.pathname !== "/"
    || url.port || !host.includes(".") || isIP(host.replace(/^\[|\]$/g, ""))
    || !/^[a-z0-9.-]+$/.test(host) || host.split(".").some(label => !/^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(label))
    || /(?:^|\.)(?:localhost|local|internal|invalid|example|test)$/.test(host)) {
    throw Error("Render API configuration must be a public HTTPS origin without credentials, path or placeholders.");
  }
  if (env.RENDER_EXTERNAL_URL && new URL(env.RENDER_EXTERNAL_URL).origin === url.origin) {
    throw Error("Frontend and API must use different service origins.");
  }
  return { result: "PASS", scope: "public_build_configuration", api_https: true, private_values_printed: false };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try { console.log(JSON.stringify(checkRenderEnvironment())); }
  catch { console.error("Render build configuration invalid: check Node pin, public HTTPS API origin and VITE_ variable names."); process.exitCode = 1; }
}
