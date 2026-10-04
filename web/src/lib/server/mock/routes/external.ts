import { MOCK_AS_OF, MOCK_NOTICE, siteById } from "../data";
import { type MockResult, ok, NO_SITE } from "../common";
import type { Schema } from "@/lib/api";

const EXT_SITE = (id: string): Schema<"ExternalSite"> | null => {
  const s = siteById(id);
  return s
    ? { id: s.id, name: s.name, kind: "sandbox-site", source: "sandbox-site", latitude: s.latitude, longitude: s.longitude, coordinate_decimals: 2, country: s.country, water_category: s.water }
    : null;
};

export function monthsBetween(p: URLSearchParams): string[] {
  const from = p.get("date_from") ?? "2023-01-01";
  const to = p.get("date_to") ?? "2023-06-30";
  const out: string[] = [];
  let y = Number(from.slice(0, 4));
  let m = Number(from.slice(5, 7));
  const endY = Number(to.slice(0, 4));
  const endM = Number(to.slice(5, 7));
  while ((y < endY || (y === endY && m <= endM)) && out.length < 60) {
    out.push(`${y}-${String(m).padStart(2, "0")}`);
    m += 1;
    if (m > 12) {
      m = 1;
      y += 1;
    }
  }
  return out;
}

export function weather(id: string, p: URLSearchParams): MockResult {
  const site = EXT_SITE(id);
  if (!site) return NO_SITE(id);
  const months = monthsBetween(p);
  const body: Schema<"WeatherResponse"> = {
    origin: "external-open-meteo",
    provider: "open-meteo-archive",
    status: "ok",
    data_kind: "modelled-reanalysis",
    dataset: "MOCK: simulated values, not Open-Meteo data",
    attribution: "Mock data. The real service credits Weather data by Open-Meteo.com.",
    attribution_url: "https://open-meteo.com/",
    attribution_verified: false,
    licence: "mock",
    data_note: "Simulated monthly values for the interface demo; aggregated to months.",
    cached: false,
    language: "en",
    flags: ["mock"],
    notices: { mock: MOCK_NOTICE },
    period: { date_from: p.get("date_from") ?? "2023-01-01", date_to: p.get("date_to") ?? "2023-06-30" },
    n_days_expected: months.length * 30,
    n_days_with_data: months.length * 30,
    site,
    data_limits: {
      model: "mock",
      day_boundary: "UTC",
      era5_delay_days: 5,
      first_day: "1940-01-01",
      last_day_requestable: "2026-09-29",
      latest_day_expected_final: "2026-09-29",
    },
    months: months.map((month, i) => ({
      month,
      days_in_window: 30,
      precipitation_n_days: 30,
      precipitation_coverage: 1,
      precipitation_sum_mm: 20 + ((i * 17) % 60),
      temperature_n_days: 30,
      temperature_coverage: 1,
      temperature_mean_c: Number((8 + i * 1.4).toFixed(1)),
      flags: [],
    })),
  };
  return ok(body);
}

export function discharge(id: string, p: URLSearchParams): MockResult {
  const site = EXT_SITE(id);
  if (!site) return NO_SITE(id);
  const months = monthsBetween(p);
  const body: Schema<"DischargeResponse"> = {
    origin: "external-open-meteo",
    provider: "open-meteo-flood",
    status: "ok",
    data_kind: "modelled-river-discharge",
    dataset: "MOCK: simulated values, not GloFAS data",
    attribution: "Mock data. The real service credits GloFAS via Open-Meteo.com.",
    attribution_url: "https://open-meteo.com/",
    attribution_verified: false,
    licence: "mock",
    data_note: "Simulated monthly means for the interface demo; not a gauge reading.",
    cached: false,
    language: "en",
    flags: ["mock"],
    notices: { mock: MOCK_NOTICE },
    period: { date_from: p.get("date_from") ?? "2023-01-01", date_to: p.get("date_to") ?? "2023-06-30" },
    n_days_expected: months.length * 30,
    n_days_with_data: months.length * 30,
    site,
    site_water_category: site.water_category ?? null,
    data_limits: {
      model: "mock",
      day_boundary: "UTC",
      first_day: "1984-01-01",
      last_day_requestable: "2026-09-29",
      documented_history_end: "2026-09-29",
      documented_history_note: "Mock.",
    },
    months: months.map((month, i) => ({
      month,
      days_in_window: 30,
      n_days: 30,
      coverage: 1,
      river_discharge_mean_m3s: Number((40 + i * 3.5).toFixed(1)),
      flags: [],
    })),
  };
  return ok(body);
}

export function species(id: string): MockResult {
  const site = EXT_SITE(id);
  if (!site) return NO_SITE(id);
  const record = (n: number, name: string): Schema<"SpeciesRecord"> => ({
    gbif_id: `mock-${n}`,
    scientific_name: name,
    latitude: site.latitude + 0.01 * n,
    longitude: site.longitude - 0.01 * n,
    distance_km: 1.2 * n,
    licence: "CC0-1.0",
    non_commercial_only: false,
    coordinate_issues: [],
    group: "fish",
    year: 2020 + n,
    dataset_name: "Mock occurrence dataset",
    citation: "Mock citation: invented record.",
  });
  const body: Schema<"SpeciesResponse"> = {
    origin: "external-gbif",
    provider: "gbif",
    status: "ok",
    data_kind: "opportunistic-occurrence-records",
    attribution: "Mock data. The real service shows each record's licence, dataset and citation from GBIF.",
    attribution_url: "https://www.gbif.org/",
    attribution_verified: false,
    licence: "mixed (mock)",
    data_note: "Invented occurrence records for the interface demo. Opportunistic, not monitoring.",
    cached: false,
    language: "en",
    flags: ["mock"],
    notices: { mock: MOCK_NOTICE },
    site,
    filters: { groups_searched: ["fish"] },
    limit: 50,
    returned: 3,
    total_records: 3,
    n_records_skipped: 0,
    licence_summary: { "CC0-1.0": 3 },
    search: { shape: "square", centre_latitude: site.latitude, centre_longitude: site.longitude, half_side_km: 5, bounds: {} },
    taxa_file: { discovered_on: MOCK_AS_OF.slice(0, 10), selection_note: "Mock taxa list." },
    group_counts: [{ group: "fish", name: "Fish", common_name: "fish", rank: "FAMILY", count: 3, caveat: "Mock." }],
    datasets: [{ dataset_key: "mock-dataset", licence: "CC0-1.0", title: "Mock occurrence dataset", citation: "Mock citation." }],
    records: [record(1, "Mock fish one"), record(2, "Mock fish two"), record(3, "Mock fish three")],
  };
  return ok(body);
}
