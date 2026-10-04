import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { mockRoute } from "@/lib/server/mock/handlers";

// The committed contract of the backend (a sibling of web/): mock answers must satisfy it at run time,
// on top of the compile-time check that comes from the generated types.
interface OpenApi {
  paths: Record<string, Record<string, { responses: Record<string, { content?: { "application/json": { schema: unknown } } }> }>>;
  components: Record<string, unknown>;
}
const spec = JSON.parse(readFileSync("../docs/openapi.json", "utf8")) as OpenApi;

const ajv = new Ajv2020({ strict: false, allErrors: true });
addFormats(ajv);

function templateFor(path: string, method: string): string | null {
  const parts = path.split("/").filter(Boolean);
  for (const template of Object.keys(spec.paths)) {
    if (!spec.paths[template]?.[method.toLowerCase()]) continue;
    const t = template.split("/").filter(Boolean);
    if (t.length === parts.length && t.every((seg, i) => (seg.startsWith("{") ? true : seg === parts[i]))) return template;
  }
  return null;
}

function validate(method: string, path: string, query = "", body: unknown = null) {
  const res = mockRoute(method, path, new URLSearchParams(query), body);
  const template = templateFor(path, method);
  expect(template, `${method} ${path} is in the contract`).not.toBeNull();
  const schema = spec.paths[template as string]?.[method.toLowerCase()]?.responses[String(res.status)]?.content?.["application/json"].schema;
  expect(schema, `${method} ${path} documents status ${res.status}`).toBeDefined();
  const check = ajv.compile({ ...(schema as object), components: spec.components });
  const ok = check(res.body);
  expect(ok, `${method} ${path}: ${JSON.stringify(check.errors?.slice(0, 3))}`).toBe(true);
}

describe("mock responses satisfy docs/openapi.json", () => {
  it.each([
    ["GET", "/countries", ""],
    ["GET", "/languages", ""],
    ["GET", "/catalog", "country=GR"],
    ["GET", "/catalog", "country=IT&language=es-MX"],
    ["GET", "/catalog", "country=NO"],
    ["GET", "/sites", "country=GR&limit=10"],
    ["GET", "/sites", "country=IT&q=po"],
    ["GET", "/sites", "country=NO&q=zzz-nothing"],
    ["GET", "/sites/mock-gr-001/measurements", "group=water-chemistry"],
    ["GET", "/sites/mock-it-001/measurements", ""],
    ["GET", "/sites/mock-gr-001/weather", "date_from=2025-01-01&date_to=2025-12-31"],
    ["GET", "/sites/mock-gr-001/discharge", "date_from=2025-01-01&date_to=2025-12-31"],
    ["GET", "/sites/mock-gr-001/species", ""],
    ["GET", "/indices/mock-gr-001", ""],
    ["GET", "/bathing-waters", "country=IT"],
    ["GET", "/bathing-waters/MOCKIT0001/samples", "limit=20"],
    ["GET", "/qc/report", ""],
    ["GET", "/reliability/campaign", "seed=7"],
    ["GET", "/review/queue", ""],
    ["GET", "/risk/mock-gr-001", ""],
  ])("%s %s?%s", (method, path, query) => validate(method, path, query));

  it.each([
    ["default", { message: "hello", country: "GR", language: "en" }],
    ["translated", { message: "hello", country: "GR", language: "es-MX", index: "water-parameters" }],
    ["unknown language", { message: "hello", language: "de" }],
    ["withheld", { message: "[mock:withheld]" }],
    ["ungrounded", { message: "[mock:ungrounded]" }],
    ["unsafe", { message: "[mock:unsafe]" }],
    ["no answer", { message: "[mock:no-answer]" }],
    ["rate limited", { message: "[mock:429]" }],
    ["bad gateway", { message: "[mock:error]" }],
  ])("POST /chat (%s)", (_name, body) => validate("POST", "/chat", "", body));

  it("is not vacuous: a body that breaks the contract is rejected", () => {
    const schema = spec.paths["/languages"]?.get?.responses["200"]?.content?.["application/json"].schema;
    const check = ajv.compile({ ...(schema as object), components: spec.components });
    expect(check({ default_language: "en" })).toBe(false);
  });

  it("documents the errors the mock returns for unknown ids and countries", () => {
    validate("GET", "/sites/unknown-id/weather", "date_from=2025-01-01&date_to=2025-12-31");
    validate("GET", "/catalog", "country=ZZ");
  });

  it("labels every mock top-level origin as synthetic or as the external provider it imitates", () => {
    for (const [path, query] of [["/countries", ""], ["/sites", "country=GR"], ["/qc/report", ""], ["/reliability/campaign", "seed=1"]] as const) {
      const body = mockRoute("GET", path, new URLSearchParams(query), null).body as { origin: string };
      expect(body.origin).toBe("synthetic");
    }
    const weather = mockRoute("GET", "/sites/mock-gr-001/weather", new URLSearchParams("date_from=2025-01-01&date_to=2025-03-31"), null).body as { dataset: string };
    expect(weather.dataset).toMatch(/MOCK/);
  });
});
