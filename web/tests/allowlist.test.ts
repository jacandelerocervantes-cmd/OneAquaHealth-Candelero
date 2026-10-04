import { describe, expect, it } from "vitest";
import { matchRoute, RULES } from "@/lib/server/allowlist";

const q = (s = "") => new URLSearchParams(s);

describe("route allow-list", () => {
  it("allows the read routes the app uses", () => {
    for (const path of ["countries", "languages", "catalog", "sites", "qc/report", "review/queue", "bathing-waters"]) {
      expect(matchRoute("GET", path.split("/"), q()), path).not.toBeNull();
    }
    expect(matchRoute("GET", ["sites", "abc", "measurements"], q())?.path).toBe("/sites/abc/measurements");
    expect(matchRoute("GET", ["bathing-waters", "IT1", "samples"], q())).not.toBeNull();
    expect(matchRoute("POST", ["chat"], q())).not.toBeNull();
  });

  it("refuses write routes, other routes, other methods and unknown paths", () => {
    expect(matchRoute("POST", ["review", "x", "decide"], q())).toBeNull();
    expect(matchRoute("POST", ["fhir", "export"], q())).toBeNull();
    expect(matchRoute("POST", ["fhir", "export", "indicators"], q())).toBeNull();
    expect(matchRoute("GET", ["docs"], q())).toBeNull();
    expect(matchRoute("GET", ["openapi.json"], q())).toBeNull();
    expect(matchRoute("GET", ["health"], q())).toBeNull();
    expect(matchRoute("GET", ["external", "status"], q())).toBeNull();
    expect(matchRoute("DELETE", ["countries"], q())).toBeNull();
    expect(matchRoute("GET", ["chat"], q())).toBeNull();
    expect(matchRoute("POST", ["countries"], q())).toBeNull();
    expect(matchRoute("GET", [], q())).toBeNull();
  });

  it("refuses path traversal and odd segments", () => {
    expect(matchRoute("GET", ["sites", "..", "measurements"], q())).toBeNull();
    expect(matchRoute("GET", ["sites", ".", "measurements"], q())).toBeNull();
    expect(matchRoute("GET", ["sites", "a/b", "measurements"], q())).toBeNull();
    expect(matchRoute("GET", ["sites", "a b", "weather"], q())).toBeNull();
    expect(matchRoute("GET", ["sites", "x".repeat(200), "weather"], q())).toBeNull();
    expect(matchRoute("GET", ["countries", "extra"], q())).toBeNull();
  });

  it("forwards only listed query parameters with valid values", () => {
    const m = matchRoute("GET", ["catalog"], q("country=GR&language=es-MX&x-api-key=evil&admin=1"));
    expect(m?.search).toBe("?country=GR&language=es-MX");
    const bad = matchRoute("GET", ["catalog"], q("country=GRC&language=%3Cscript%3E"));
    expect(bad?.search).toBe("");
    const sites = matchRoute("GET", ["sites"], q("limit=999999999&offset=-1&source=real-sandbox&q=po"));
    expect(sites?.search).toBe("?source=real-sandbox&q=po");
  });

  it("encodes the validated segments", () => {
    expect(matchRoute("GET", ["indices", "a:b~c"], q())?.path).toBe("/indices/a%3Ab~c");
  });

  it("lists no write route", () => {
    expect(RULES.filter((r) => r.method === "POST").map((r) => r.template)).toEqual(["/chat"]);
  });
});

describe("allow-list properties (seeded fuzz)", () => {
  // A small deterministic generator keeps the test reproducible without extra dependencies.
  function rng(seed: number) {
    let x = seed;
    return () => {
      x = (x * 1664525 + 1013904223) % 4294967296;
      return x / 4294967296;
    };
  }
  const alphabet = ["a", "Z", "0", "-", "_", ".", "..", "/", "%", "%2e", "%2f", " ", "?", "#", "\\", "é", "\u0000", ":", "~", "{}", "sites", "chat", "decide", "export"];

  it("never lets a path with traversal or unlisted characters through, and only matches listed templates", () => {
    const next = rng(20261004);
    const templates = new Set(RULES.map((r) => r.template.split("/").filter(Boolean).map((p) => (p === "{}" ? "*" : p)).join("/")));
    let matched = 0;
    for (let i = 0; i < 3000; i += 1) {
      const junk = () => Array.from({ length: 1 + Math.floor(next() * 3) }, () => alphabet[Math.floor(next() * alphabet.length)]).join("");
      const rule = RULES[Math.floor(next() * RULES.length)]!;
      // Start from a listed template and fill its placeholders with valid ids or junk.
      const segments = rule.template.split("/").filter(Boolean).map((p) => (p === "{}" ? (next() < 0.5 ? `id${Math.floor(next() * 99)}` : junk()) : p));
      if (next() < 0.2) segments.push(junk());
      const n = segments.length;
      const method = next() < 0.8 ? rule.method : rule.method === "GET" ? "POST" : "GET";
      const m = matchRoute(method, segments, new URLSearchParams(`country=${segments[0]}&limit=${segments[n - 1]}&evil=1`));
      if (!m) continue;
      matched += 1;
      expect(m.path).toMatch(/^\/[A-Za-z0-9._:~%/-]+$/);
      expect(m.path.split("/")).not.toContain("..");
      expect(m.search).not.toContain("evil");
      const shape = m.path.split("/").filter(Boolean).map((p, idx) => (m.rule.template.split("/").filter(Boolean)[idx] === "{}" ? "*" : p)).join("/");
      expect(templates.has(shape)).toBe(true);
    }
    expect(matched).toBeGreaterThan(20);
  });
});
