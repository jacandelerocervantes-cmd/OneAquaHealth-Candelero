/**
 * Simulated data for the offline mock mode (OAH_DATA_MODE=mock). Every value here is invented
 * for the interface demo: it is NOT real monitoring data, and every top-level `origin` that has
 * a "synthetic" value says so. Shapes are typed from docs/openapi.json, so the compiler and
 * tests/mock-contract.test.ts keep them in line with the backend contract.
 */
import type { Schema } from "@/lib/api";

export const MOCK_AS_OF = "2026-10-04T00:00:00Z";
export const MOCK_NOTICE =
  "MOCK DATA: simulated values for the interface demo. Not measurements, not a compliance assessment, not a health or safety statement.";
export const MOCK_DISCLAIMER =
  "AI-generated from tool results, not verified. Screening against reference values, not legal compliance; never a potability, health or regulatory determination.";

export const freshness: Schema<"DataFreshnessModel"> = { status: "snapshot", as_of: MOCK_AS_OF, age_seconds: 0 };

export type CountryCode = "GR" | "IT" | "NO";
export const COUNTRY_CODES: readonly CountryCode[] = ["GR", "IT", "NO"];

export const COUNTRY_NAMES: Record<CountryCode, string> = { GR: "Greece", IT: "Italy", NO: "Norway" };

const store = (state: "ready" | "not-built", detail: string) => ({
  state,
  detail,
  edition: state === "ready" ? "mock" : null,
  build_date_utc: state === "ready" ? MOCK_AS_OF : null,
  attribution: state === "ready" ? "Mock attribution: no real provider data in this response." : null,
});

export const stores = {
  waterbase: store("ready", "Mock Waterbase store"),
  bathing_water: store("ready", "Mock bathing-water classification store"),
  bathing_samples: store("ready", "Mock bathing-samples store"),
};

/** Per-country availability that drives the catalogue (NO has no Directive bathing data). */
export const HAS_BATHING: Record<CountryCode, boolean> = { GR: true, IT: true, NO: false };

export const mockCountries: Schema<"CountriesResponse"> = {
  origin: "synthetic",
  data_freshness: freshness,
  interpretation_notice: MOCK_NOTICE,
  sites_without_country: 0,
  waterbase: stores.waterbase,
  bathing_water: stores.bathing_water,
  bathing_samples: stores.bathing_samples,
  countries: COUNTRY_CODES.map((code) => ({
    code,
    status: "eu-values-only" as const,
    evaluated_sites: 4,
    total_sites: 4,
    skipped_sites: 0,
    skipped_non_water_sites: 0,
    measurement_only_sites: 0,
    has_national_limits: false,
    limit_sources: [],
    latest_year: 2024,
    parameter_groups: ["water-chemistry", "solids-turbidity", "organic-matter"] as Schema<"Country">["parameter_groups"],
  })),
};

interface Tier {
  code: string;
  name: string;
  endonym: string;
  script: string;
  tier: 1 | 2;
}

const LANGS: Tier[] = [
  { code: "bg", name: "Bulgarian", endonym: "Български", script: "Cyrillic", tier: 2 },
  { code: "hr", name: "Croatian", endonym: "Hrvatski", script: "Latin", tier: 2 },
  { code: "cs", name: "Czech", endonym: "Čeština", script: "Latin", tier: 2 },
  { code: "da", name: "Danish", endonym: "Dansk", script: "Latin", tier: 2 },
  { code: "nl", name: "Dutch", endonym: "Nederlands", script: "Latin", tier: 2 },
  { code: "en", name: "English (source)", endonym: "English", script: "Latin", tier: 1 },
  { code: "et", name: "Estonian", endonym: "Eesti", script: "Latin", tier: 2 },
  { code: "fi", name: "Finnish", endonym: "Suomi", script: "Latin", tier: 2 },
  { code: "fr", name: "French", endonym: "Français", script: "Latin", tier: 1 },
  { code: "de", name: "German", endonym: "Deutsch", script: "Latin", tier: 1 },
  { code: "el", name: "Greek", endonym: "Ελληνικά", script: "Greek", tier: 1 },
  { code: "hu", name: "Hungarian", endonym: "Magyar", script: "Latin", tier: 2 },
  { code: "ga", name: "Irish", endonym: "Gaeilge", script: "Latin", tier: 2 },
  { code: "it", name: "Italian", endonym: "Italiano", script: "Latin", tier: 1 },
  { code: "lv", name: "Latvian", endonym: "Latviešu", script: "Latin", tier: 2 },
  { code: "lt", name: "Lithuanian", endonym: "Lietuvių", script: "Latin", tier: 2 },
  { code: "mt", name: "Maltese", endonym: "Malti", script: "Latin", tier: 2 },
  { code: "nb", name: "Norwegian Bokmål", endonym: "Norsk bokmål", script: "Latin", tier: 1 },
  { code: "pl", name: "Polish", endonym: "Polski", script: "Latin", tier: 2 },
  { code: "pt", name: "Portuguese", endonym: "Português", script: "Latin", tier: 1 },
  { code: "ro", name: "Romanian", endonym: "Română", script: "Latin", tier: 2 },
  { code: "sk", name: "Slovak", endonym: "Slovenčina", script: "Latin", tier: 2 },
  { code: "sl", name: "Slovenian", endonym: "Slovenščina", script: "Latin", tier: 2 },
  { code: "es-MX", name: "Spanish (Mexico)", endonym: "Español (México)", script: "Latin", tier: 1 },
  { code: "es-ES", name: "Spanish (Spain)", endonym: "Español (España)", script: "Latin", tier: 1 },
  { code: "sv", name: "Swedish", endonym: "Svenska", script: "Latin", tier: 2 },
];

export const mockLanguages: Schema<"LanguagesResponse"> = {
  default_language: "en",
  source_language: "en",
  note: "Mock list of the 26 answer languages; English is the source.",
  languages: LANGS.map((l) => ({
    code: l.code,
    name: l.name,
    endonym: l.endonym,
    script: l.script,
    direction: "ltr" as const,
    tier: l.tier,
    status: l.code === "en" ? ("source" as const) : ("translated-by-model" as const),
    fixed_strings_review_status: l.code === "en" ? ("source" as const) : ("machine-draft" as const),
    translation_checks: l.code === "en" ? null : l.tier === 1 ? ("neutral-and-denylist" as const) : ("neutral-only" as const),
  })),
};

interface MockSite {
  id: string;
  name: string;
  country: CountryCode;
  latitude: number;
  longitude: number;
  water: "river" | "lake";
  ui: Schema<"Site">["ui_status"];
}

export const MOCK_SITES: readonly MockSite[] = [
  { id: "mock-gr-001", name: "Mock River Alpha", country: "GR", latitude: 39.19, longitude: 22.76, water: "river", ui: "good" },
  { id: "mock-gr-002", name: "Mock Lake Beta", country: "GR", latitude: 40.64, longitude: 22.94, water: "lake", ui: "moderate" },
  { id: "mock-gr-003", name: "Mock River Gamma", country: "GR", latitude: 37.98, longitude: 23.73, water: "river", ui: "poor" },
  { id: "mock-gr-004", name: "Mock Stream Delta", country: "GR", latitude: 35.34, longitude: 25.14, water: "river", ui: "unavailable" },
  { id: "mock-it-001", name: "Mock Po Reach", country: "IT", latitude: 45.05, longitude: 9.7, water: "river", ui: "moderate" },
  { id: "mock-it-002", name: "Mock Lake Garda Shore", country: "IT", latitude: 45.6, longitude: 10.7, water: "lake", ui: "good" },
  { id: "mock-it-003", name: "Mock Tiber Reach", country: "IT", latitude: 41.9, longitude: 12.48, water: "river", ui: "poor" },
  { id: "mock-it-004", name: "Mock Arno Reach", country: "IT", latitude: 43.77, longitude: 11.25, water: "river", ui: "good" },
  { id: "mock-no-001", name: "Mock Glomma Reach", country: "NO", latitude: 59.28, longitude: 11.13, water: "river", ui: "good" },
  { id: "mock-no-002", name: "Mock Lake Mjøsa", country: "NO", latitude: 60.8, longitude: 10.7, water: "lake", ui: "good" },
  { id: "mock-no-003", name: "Mock Fjord Inlet", country: "NO", latitude: 60.39, longitude: 5.32, water: "lake", ui: "moderate" },
  { id: "mock-no-004", name: "Mock Tana Reach", country: "NO", latitude: 70.0, longitude: 28.2, water: "river", ui: "unavailable" },
];

export function siteById(id: string): MockSite | undefined {
  return MOCK_SITES.find((s) => s.id === id);
}

export interface MockBathingWater {
  id: string;
  name: string;
  country: CountryCode;
  latitude: number;
  longitude: number;
  quality: string;
  qualityClass: string;
}

export const MOCK_BATHING: readonly MockBathingWater[] = [
  { id: "MOCKGR0001", name: "Mock Beach Aegean", country: "GR", latitude: 38.0, longitude: 23.9, quality: "Excellent", qualityClass: "1" },
  { id: "MOCKGR0002", name: "Mock Beach Ionian", country: "GR", latitude: 39.6, longitude: 19.9, quality: "Good", qualityClass: "2" },
  { id: "MOCKIT0001", name: "Mock Beach Adriatic", country: "IT", latitude: 44.1, longitude: 12.4, quality: "Excellent", qualityClass: "1" },
  { id: "MOCKIT0002", name: "Mock Beach Tyrrhenian", country: "IT", latitude: 41.2, longitude: 13.6, quality: "Sufficient", qualityClass: "3" },
];
