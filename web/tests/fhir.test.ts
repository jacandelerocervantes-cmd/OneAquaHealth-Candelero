import { describe, expect, it } from "vitest";
import type { Schema } from "@/lib/api";
import { fhirFilename, measurementsBundle } from "@/lib/fhir";
import { matchRoute } from "@/lib/server/allowlist";
import { mockRoute } from "@/lib/server/mock/handlers";

type Bundle = { resourceType: string; type: string; entry: { fullUrl: string; resource: Record<string, unknown> & { resourceType: string; id: string } }[] };

const NOW = new Date("2026-10-04T12:00:00Z");
let counter = 0;
const uuid = () => `00000000-0000-4000-8000-${String((counter += 1)).padStart(12, "0")}`;

function payload(records: Partial<Schema<"MeasurementRecord">>[]): Schema<"SiteMeasurementsResponse"> {
  const base = { status: "within-limit", limit_regime: "none", data_quality_flags: [], source: "real-eea-waterbase", origin: "real-eea-waterbase", unit: "mg/L", parameter: "Nitrate" } as const;
  return {
    origin: "real-eea-waterbase", source: "real-eea-waterbase", resolution: "annual", location_id: "IT01-001025", attribution: "EEA Waterbase (CC BY 4.0)",
    data_freshness: { status: "snapshot", as_of: "2026-10-04T00:00:00Z", age_seconds: 0 }, interpretation_notice: "n", limit: 200, returned: records.length,
    total_matching: records.length, truncated: false, records: records.map((r) => ({ ...base, ...r })),
  } as Schema<"SiteMeasurementsResponse">;
}

const types = (b: Bundle, type: string) => b.entry.map((e) => e.resource).filter((r) => r.resourceType === type);

describe("the FHIR Bundle of a site's measurements", () => {
  it("has a Location, an Observation per value, and a Provenance that targets every Observation", () => {
    const b = measurementsBundle(payload([{ value: 2.5, comparator: "<", year: 2020, statistic: "mean", n: 4 }, { value: 7.4, parameter: "pH", unit: "[pH]", period_start: "2020-01-01", period_end: "2020-12-31" }]), { id: "IT01-001025", name: "Revello", latitude: 44.6, longitude: 7.4 }, NOW, uuid) as unknown as Bundle;
    expect(b.resourceType).toBe("Bundle");
    expect(b.type).toBe("collection");
    const [location] = types(b, "Location");
    expect(location?.name).toBe("Revello");
    expect(location?.position).toEqual({ longitude: 7.4, latitude: 44.6 });
    const observations = types(b, "Observation");
    expect(observations).toHaveLength(2);
    const provenance = types(b, "Provenance")[0] as unknown as { target: { reference: string }[] };
    const urls = b.entry.filter((e) => e.resource.resourceType === "Observation").map((e) => e.fullUrl);
    expect(provenance.target.map((t) => t.reference)).toEqual(urls);
  });

  it("invents no code: parameters are text only and a UCUM code appears only for units written the UCUM way", () => {
    const b = measurementsBundle(payload([{ value: 2.5 }, { value: 7.4, parameter: "pH", unit: "[pH]" }]), null, NOW, uuid) as unknown as Bundle;
    expect(JSON.stringify(b)).not.toContain('"coding"');
    const [nitrate, ph] = types(b, "Observation") as unknown as { code: Record<string, unknown>; valueQuantity: Record<string, unknown> }[];
    expect(Object.keys(nitrate?.code ?? {})).toEqual(["text"]);
    expect(nitrate?.valueQuantity).toMatchObject({ unit: "mg/L", system: "http://unitsofmeasure.org", code: "mg/L" });
    expect(ph?.valueQuantity).toEqual({ value: 7.4, unit: "[pH]" });
  });

  it("leaves out records without a value, keeps real comparators only, and tags the origin", () => {
    const b = measurementsBundle(payload([{ value: null, parameter: "Turbidity" }, { value: 1, comparator: "~" }, { value: 2, comparator: ">=", month: 3, year: 2021 }]), null, NOW, uuid) as unknown as Bundle;
    const observations = types(b, "Observation") as unknown as { valueQuantity: Record<string, unknown>; effectiveDateTime?: string; meta: { tag: { code: string }[] } }[];
    expect(observations).toHaveLength(2);
    expect(observations[0]?.valueQuantity.comparator).toBeUndefined();
    expect(observations[1]?.valueQuantity.comparator).toBe(">=");
    expect(observations[1]?.effectiveDateTime).toBe("2021-03");
    expect(observations.every((o) => o.meta.tag[0]?.code === "real-eea-waterbase")).toBe(true);
  });

  it("builds a safe file name", () => {
    expect(fhirFilename("IT01/001 025")).toBe("measurements-IT01-001-025-fhir.json");
  });
});

describe("the mock backend and the proxy allow-list", () => {
  it("the mock serves the Bundle of a mock site, every resource tagged synthetic", () => {
    const res = mockRoute("GET", "/sites/mock-gr-001/fhir", new URLSearchParams("group=water-chemistry"), null);
    expect(res.status).toBe(200);
    const b = res.body as unknown as Bundle;
    expect(b.resourceType).toBe("Bundle");
    expect(types(b, "Observation").length).toBeGreaterThan(0);
    for (const e of b.entry) {
      const tags = ((e.resource.meta as { tag?: { code: string }[] } | undefined)?.tag ?? []).map((t) => t.code);
      if (e.resource.resourceType === "Observation") expect(tags).toEqual(["synthetic"]);
    }
    expect(mockRoute("GET", "/sites/nope/fhir", new URLSearchParams(), null).status).toBe(404);
  });

  it("the allow-list lets the same query as the measurements through and nothing else", () => {
    const q = (s: string) => new URLSearchParams(s);
    const m = matchRoute("GET", ["sites", "mock-gr-001", "fhir"], q("group=water-chemistry&resolution=annual&limit=200&x-api-key=evil&admin=1"));
    expect(m?.path).toBe("/sites/mock-gr-001/fhir");
    expect(m?.search).toBe("?group=water-chemistry&resolution=annual&limit=200");
    expect(matchRoute("POST", ["sites", "mock-gr-001", "fhir"], q(""))).toBeNull();
    expect(matchRoute("GET", ["fhir", "export"], q(""))).toBeNull();
  });
});
