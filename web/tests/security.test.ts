import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";
import { buildCsp, OSM_TILE_HOST, securityHeaders } from "@/lib/csp";
import { DEFAULT_SETTINGS, sanitiseSettings } from "@/lib/client/settings-store";
import { bathingToPlaces, indexIdFromPath, OSM_ATTRIBUTION, OSM_TILES, sitesToPlaces } from "@/components/map-pane";
import { mockRoute } from "@/lib/server/mock/handlers";
import type { Schema, SitesResponse } from "@/lib/api";

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(ts|tsx|css|mjs)$/.test(name) ? [path] : [];
  });
}

const SRC = sources("src").filter((p) => !p.endsWith("api-types.ts"));
const read = (p: string) => readFileSync(p, "utf8");

describe("the browser never holds a secret and renders only plain text", () => {
  it("uses no raw HTML injection anywhere", () => {
    for (const p of SRC) {
      const text = read(p);
      expect(text, p).not.toMatch(/dangerouslySetInnerHTML/);
      expect(text, p).not.toMatch(/\.innerHTML\s*=/);
      expect(text, p).not.toMatch(/\binsertAdjacentHTML\b/);
      expect(text, p).not.toMatch(/\beval\s*\(/);
    }
  });

  it("reads the backend URL and key only in the server configuration module", () => {
    const readers = SRC.filter((p) => /OAH_API_KEY|OAH_BACKEND_URL/.test(read(p)));
    expect(readers.map((p) => relative("src", p))).toEqual(["lib/server/config.ts"]);
  });

  it("exposes no NEXT_PUBLIC_ variable and never ships the key header from client code", () => {
    for (const p of SRC) {
      expect(read(p), p).not.toMatch(/NEXT_PUBLIC_/);
      if (!p.includes("lib/server")) expect(read(p), p).not.toMatch(/x-api-key/i);
    }
  });

  it("keeps server modules out of client code", () => {
    for (const p of SRC.filter((f) => !f.includes("lib/server") && !f.includes("src/app/api") && !f.endsWith("proxy.ts"))) {
      expect(read(p), p).not.toMatch(/from "@\/lib\/server/);
      expect(read(p), p).not.toMatch(/from "node:/);
    }
  });

  it("calls only same-origin routes from the browser", () => {
    for (const p of SRC.filter((f) => !f.includes("lib/server"))) {
      expect(read(p), p).not.toMatch(/fetch\(\s*["'`]https?:/);
    }
  });

  it("is portable: no absolute path or machine marker in the sources", () => {
    const absolute = /(?<![A-Za-z0-9])[A-Za-z]:[\\/]|(?<!:)\/(?:Users|home|tmp|var|opt)\//;
    for (const p of [...SRC, ...sources("tests"), "package.json", "README.md", "env.example"]) {
      if (p.endsWith("security.test.ts")) continue;
      expect(read(p), p).not.toMatch(absolute);
    }
  });

  it("opens every external link safely", () => {
    for (const p of SRC.filter((f) => f.endsWith(".tsx"))) {
      for (const tag of read(p).match(/<a\b[^>]*target="_blank"[^>]*>/g) ?? []) expect(tag, p).toContain("noopener");
    }
  });
});

describe("security headers", () => {
  const csp = buildCsp("abc123");

  it("lists only what the app uses and nothing unsafe for scripts", () => {
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("script-src 'self' 'nonce-abc123'");
    expect(csp).not.toContain("'unsafe-eval'");
    expect(csp).not.toMatch(/script-src[^;]*'unsafe-inline'/);
    expect(csp).toContain("connect-src 'self'");
    expect(csp).toContain(`img-src 'self' data: ${OSM_TILE_HOST}`);
    for (const d of ["frame-ancestors 'none'", "base-uri 'self'", "form-action 'self'", "object-src 'none'"]) expect(csp).toContain(d);
  });

  it("allows eval only in development", () => {
    expect(buildCsp("n", true)).toContain("'unsafe-eval'");
  });

  it("sets the other headers of the pre-deploy checklist", () => {
    const h = securityHeaders("n");
    expect(h["Referrer-Policy"]).toBe("strict-origin-when-cross-origin");
    expect(h["X-Content-Type-Options"]).toBe("nosniff");
    expect(h["X-Frame-Options"]).toBe("DENY");
    expect(h["Strict-Transport-Security"]).toMatch(/max-age=31536000/);
    expect(h["Permissions-Policy"]).toMatch(/camera=\(\).*microphone=\(\).*geolocation=\(\).*payment=\(\)/);
  });
});

describe("map pane helpers", () => {
  it("uses OpenStreetMap tiles with the required attribution", () => {
    expect(OSM_TILES.startsWith(OSM_TILE_HOST)).toBe(true);
    expect(OSM_ATTRIBUTION).toContain("OpenStreetMap");
    expect(OSM_ATTRIBUTION).toContain("https://www.openstreetmap.org/copyright");
  });

  it("derives the index from the path", () => {
    expect(indexIdFromPath("/i/bathing-classes")).toBe("bathing-classes");
    expect(indexIdFromPath("/labs/river-risk")).toBe("river-risk");
    expect(indexIdFromPath("/")).toBeNull();
    expect(indexIdFromPath("/settings")).toBeNull();
  });

  it("maps sites and bathing waters to places, keeping places without a location out of the map", () => {
    const sites = mockRoute("GET", "/sites", new URLSearchParams("country=IT"), null).body as SitesResponse;
    const places = sitesToPlaces(sites, "IT");
    expect(places).toHaveLength(4);
    expect(places.every((p) => p.kind === "site" && p.latitude !== null)).toBe(true);
    const waters = mockRoute("GET", "/bathing-waters", new URLSearchParams("country=GR"), null).body as Schema<"BathingWatersResponse">;
    waters.bathing_waters[0]!.latitude = null;
    const bw = bathingToPlaces(waters);
    expect(bw[0]!.latitude).toBeNull();
    expect(bw[1]!.kind).toBe("bathing-water");
  });
});

describe("stored settings", () => {
  it("falls back to the defaults for anything malformed", () => {
    expect(sanitiseSettings(null)).toEqual(DEFAULT_SETTINGS);
    expect(sanitiseSettings({ country: "greece", language: "<script>" })).toEqual(DEFAULT_SETTINGS);
    expect(sanitiseSettings({ defaultCountry: "IT", country: "NO", defaultLanguage: "de", language: "es-MX" })).toEqual({
      defaultCountry: "IT",
      country: "NO",
      defaultLanguage: "de",
      language: "es-MX",
    });
  });
});
