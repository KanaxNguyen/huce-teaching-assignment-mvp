// Builds the static export for Cloudflare Pages. The Next.js route handler cannot be part of an
// export, so it is hidden (a folder starting with "_" is private to the app router) during the
// build and always restored; functions/api/backend/[[path]].ts serves the same BFF on Pages.
import { existsSync, renameSync } from "node:fs";
import { spawnSync } from "node:child_process";

const live = "app/api";
const hidden = "app/_api";
if (existsSync(hidden)) throw new Error(`${hidden} already exists; restore it before building.`);

renameSync(live, hidden);
let status = 1;
try {
  const result = spawnSync("npx", ["next", "build"], { stdio: "inherit", env: { ...process.env, STATIC_EXPORT: "1" } });
  status = result.status ?? 1;
} finally {
  renameSync(hidden, live);
}
process.exit(status);
