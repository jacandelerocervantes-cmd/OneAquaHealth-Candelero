import { MOCK_NOTICE, MOCK_SITES, freshness, siteById, stores } from "../data";
import { type MockResult, ok, err, asCountry, NO_SITE } from "../common";
import type { Schema } from "@/lib/api";
import { measurementsBundle } from "@/lib/fhir";

export function sites(p: URLSearchParams): MockResult {
  const country = p.get("country") ? asCountry(p.get("country")) : null;
  if (p.get("country") && !country) return err(422, "Unknown country; known codes: GR, IT, NO.");
  const q = (p.get("q") ?? "").toLowerCase();
  const limit = Math.min(Number(p.get("limit") ?? 200) || 200, 500);
  const offset = Number(p.get("offset") ?? 0) || 0;
  const matching = MOCK_SITES.filter((s) => (!country || s.country === country) && (!q || s.name.toLowerCase().includes(q)));
  const page = matching.slice(offset, offset + limit);
  const body: Schema<"SitesResponse"> = {
    origin: "synthetic",
    data_freshness: freshness,
    interpretation_notice: MOCK_NOTICE,
    limit,
    offset,
    returned: page.length,
    total_matching: matching.length,
    truncated: offset + page.length < matching.length,
    sources: ["real-sandbox"],
    waterbase: stores.waterbase,
    sites: page.map((s) => ({
      id: s.id,
      name: s.name,
      kind: "water-body" as const,
      latitude: s.latitude,
      longitude: s.longitude,
      status: "evaluated" as const,
      ui_status: s.ui,
      water_category: s.water,
      limit_country: s.country,
      location_status: "located" as const,
      eclipsed: false,
      veto_triggered: false,
      // The contract has no "synthetic" value here; the label users see is `origin` ("synthetic").
      source: "real-sandbox" as const,
      origin: "synthetic" as const,
    })),
  };
  return ok(body);
}

export function measurements(id: string, p: URLSearchParams): MockResult {
  const site = siteById(id);
  if (!site) return NO_SITE(id);
  const parameters = [
    { name: "Total phosphorus", unit: "mg/L", group: "water-chemistry" as const, base: 0.06 },
    { name: "Nitrate", unit: "mg/L", group: "water-chemistry" as const, base: 2.1 },
    { name: "Total suspended solids", unit: "mg/L", group: "solids-turbidity" as const, base: 11 },
    { name: "Biochemical oxygen demand", unit: "mg/L", group: "organic-matter" as const, base: 2.4 },
  ];
  const group = p.get("group");
  const wanted = parameters.filter((x) => !group || x.group === group);
  const records: Schema<"MeasurementRecord">[] = wanted.flatMap((x, i) =>
    [2021, 2022, 2023, 2024].map((year, j) => ({
      parameter: x.name,
      group: x.group,
      unit: x.unit,
      value: Number((x.base * (1 + 0.05 * j + 0.02 * i)).toFixed(3)),
      statistic: "mean",
      n: 12,
      year,
      period_start: `${year}-01-01`,
      period_end: `${year}-12-31`,
      status: "indeterminate" as const,
      limit_regime: "none",
      data_quality_flags: [],
      source: "real-sandbox" as const,
      origin: "synthetic" as const,
    })),
  );
  const body: Schema<"SiteMeasurementsResponse"> = {
    origin: "synthetic",
    data_freshness: freshness,
    interpretation_notice: MOCK_NOTICE,
    attribution: "Mock data: no provider attribution applies.",
    location_id: id,
    limit: Number(p.get("limit") ?? 200) || 200,
    returned: records.length,
    total_matching: records.length,
    truncated: false,
    resolution: "annual",
    source: "real-sandbox",
    records,
  };
  return ok(body);
}

/** The mock of `GET /sites/{id}/fhir`: the mock measurements as a Bundle (every resource is tagged synthetic). */
export function fhir(id: string, p: URLSearchParams): MockResult {
  const site = siteById(id);
  const res = measurements(id, p);
  if (!site || res.status !== 200) return res;
  return ok(measurementsBundle(res.body as Schema<"SiteMeasurementsResponse">, { id, name: site.name, latitude: site.latitude, longitude: site.longitude }));
}

export function indexFor(id: string): MockResult {
  if (!siteById(id)) return NO_SITE(id);
  const body: Schema<"IndexResponse"> = {
    origin: "synthetic",
    status: "evaluated",
    location_ref: id,
    data_quality: { note: "mock", records: 48 },
    objective_limits_source: "MOCK: no reference limits are applied to simulated values.",
    data_freshness: freshness,
    interpretation_notice: MOCK_NOTICE,
  };
  return ok(body);
}
