// Guard both production output and the browser module graph. No file contents
// or credential values are included in build errors.
import { isAbsolute, relative, resolve } from "node:path";

const privateName = /(?:^|[\\/])(?:\.env(?:\.[^\\/]*)?|[^\\/]*\.(?:db|sqlite|sqlite3)(?:-(?:wal|shm|journal))?|[^\\/]*\.(?:pem|key|p12|pfx))$/i;
const privateContent = /SQLite format 3\x00|-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----|\$argon2id\$v=\d+\$/;

export function privateDataBoundary(root) {
  const frontend = resolve(root);
  return {
    name: "private-data-boundary",
    generateBundle(_options, bundle) {
      for (const entry of Object.values(bundle)) {
        if (privateName.test(entry.fileName)) this.error("Private files cannot be published by the frontend.");
        const content = entry.type === "chunk" ? entry.code : typeof entry.source === "string" ? entry.source : Buffer.from(entry.source).toString("utf8");
        if (privateContent.test(content)) this.error("Private data cannot be published by the frontend.");
        if (entry.type !== "chunk") continue;
        for (const id of Object.keys(entry.modules)) {
          if (id.startsWith("\0")) continue;
          const file = id.split("?", 1)[0];
          const child = relative(frontend, file);
          if (privateName.test(file) || (isAbsolute(file) && (isAbsolute(child) || child === ".." || child.startsWith("..\\") || child.startsWith("../")))) {
            this.error("Browser modules must stay inside the frontend and exclude private files.");
          }
        }
      }
    },
  };
}
