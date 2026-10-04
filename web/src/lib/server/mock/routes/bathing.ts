import { MOCK_BATHING, MOCK_NOTICE, freshness, stores } from "../data";
import { type MockResult, ok, err, asCountry } from "../common";
import type { Schema } from "@/lib/api";

export function bathingList(p: URLSearchParams): MockResult {
  const country = p.get("country") ? asCountry(p.get("country")) : null;
  const q = (p.get("q") ?? "").toLowerCase();
  const matching = MOCK_BATHING.filter((b) => (!country || b.country === country) && (!q || b.name.toLowerCase().includes(q)));
  const body: Schema<"BathingWatersResponse"> = {
    origin: "real-eea-bathing-water",
    attribution: "Mock bathing-water entries (invented): no EEA data in this response.",
    notice: MOCK_NOTICE,
    bathing_water: stores.bathing_water,
    data_freshness: freshness,
    limit: 200,
    offset: 0,
    returned: matching.length,
    total_matching: matching.length,
    truncated: false,
    bathing_waters: matching.map((b) => ({
      id: b.id,
      name: b.name,
      country: b.country,
      latitude: b.latitude,
      longitude: b.longitude,
      location_status: "located" as const,
      first_season: 2015,
      latest_season: 2024,
      n_seasons: 10,
      latest_quality: b.quality,
      latest_quality_class: b.qualityClass,
      type: "coastal",
      origin: "real-eea-bathing-water" as const,
      source: "real-eea-bathing-water" as const,
    })),
  };
  return ok(body);
}

export function bathingSamples(id: string): MockResult {
  const bw = MOCK_BATHING.find((b) => b.id === id);
  if (!bw) return err(404, `Unknown bathing water: ${id}`);
  const ind = (max: number, mean: number) => ({
    n_samples_in_range: 40,
    n_quantified: 36,
    n_confirmed_high: 1,
    n_detection_limit: 3,
    n_missing: 0,
    n_unrecognised: 0,
    min: 5,
    max,
    mean,
    median: mean - 20,
  });
  const body: Schema<"BathingSamplesResponse"> = {
    origin: "real-eea-bathing-samples",
    attribution: "Mock sample summary (invented): no EEA data in this response.",
    notice: MOCK_NOTICE,
    no_threshold_notice: "No threshold or limit is applied to these concentrations.",
    flagged_values_note: "Mock: flagged values are counted apart.",
    unit: "cfu/100 ml",
    unit_statement: "Colony-forming units per 100 ml.",
    language: "en",
    flags: ["mock"],
    bathing_samples: stores.bathing_samples,
    bathing_water: { id: bw.id, country: bw.country, name: bw.name, type: "coastal" },
    data_freshness: freshness,
    filters: { order: "desc" },
    limit: 20,
    returned: 0,
    total_matching: 40,
    truncated: true,
    samples: [],
    summary: { escherichia_coli: ind(180, 62), intestinal_enterococci: ind(95, 31) },
  };
  return ok(body);
}
