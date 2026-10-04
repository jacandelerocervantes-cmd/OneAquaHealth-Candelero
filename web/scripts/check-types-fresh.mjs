// Fails when src/lib/api-types.ts is not what `npm run types` would generate from docs/openapi.json.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "oah-types-"));
const out = join(dir, "api-types.ts");
try {
  execFileSync("npx", ["openapi-typescript", "../docs/openapi.json", "-o", out], { stdio: "ignore" });
  const fresh = readFileSync(out, "utf8");
  const current = readFileSync("src/lib/api-types.ts", "utf8");
  if (fresh !== current) {
    console.error("src/lib/api-types.ts is stale: run `npm run types`.");
    process.exit(1);
  }
  console.log("api-types.ts is up to date with docs/openapi.json.");
} finally {
  rmSync(dir, { recursive: true, force: true });
}
