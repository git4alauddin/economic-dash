import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { privateDataBoundary } from "./scripts/private-data-boundary.mjs";

const frontendRoot = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  plugins: [react(), privateDataBoundary(frontendRoot)],
  // Import reviewed assets explicitly; public/ would bypass fs.deny filtering.
  publicDir: false,
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    fs: {
      strict: true,
      allow: [frontendRoot],
      deny: [".env", ".env.*", "**/.git/**", "**/*.{crt,pem,key,p12,pfx}",
        "**/*.{db,sqlite,sqlite3}", "**/*.{db,sqlite,sqlite3}-{wal,shm,journal}"],
    },
  },
});
