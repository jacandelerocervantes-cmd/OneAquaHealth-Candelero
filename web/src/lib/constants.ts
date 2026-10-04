import type { ChatResponse } from "./api";
import { msg } from "./i18n-core";

/** Texts declared here are wrapped in `msg()` (so they are extracted for translation) and shown through `t()`. */

/** The fixed notice shown on every screen. It is a constant of the app, never model output. */
export const FIXED_NOTICE = msg(
  "Screening against reference values, not legal compliance. No health or safety verdicts. AI answers are generated from tool results and are not verified.",
);

export const FALLBACK_DISCLAIMER = msg(
  "AI-generated from tool results, not verified. Screening against reference values, not legal compliance; never a potability, health or regulatory determination.",
);

export const DEFAULT_LANGUAGE = "en";
export const DEFAULT_COUNTRY = "GR";
export const SOURCE_LANGUAGE = "en";
export const MAX_MESSAGE_LENGTH = 500;
export const MAX_HISTORY_TURNS = 6;

export const COUNTRY_NAMES: Record<string, string> = { GR: "Greece", IT: "Italy", NO: "Norway" };

export const USER_LABEL = msg("Judge account");

type Origin = ChatResponse["origin"];

export interface OriginInfo {
  label: string;
  kind: "real" | "external" | "synthetic";
  hint: string;
}

/** Labels for every origin value of the contract; real, external and synthetic never share a label. */
export const ORIGINS: Record<Origin, OriginInfo> = {
  "real-sandbox": { label: msg("Real · HL7 Europe sandbox"), kind: "real", hint: msg("Real data from the HL7 Europe sandbox.") },
  "real-eea-waterbase": { label: msg("Real · EEA Waterbase"), kind: "real", hint: msg("Real data from the EEA Waterbase 2026 store.") },
  "real-eea-bathing-water": { label: msg("Real · EEA bathing water"), kind: "real", hint: msg("Real classification from the EEA Bathing Water Directive data.") },
  "real-eea-bathing-samples": { label: msg("Real · EEA bathing samples"), kind: "real", hint: msg("Real monitoring results from the EEA Discodata bathing-water table.") },
  "external-open-meteo": { label: msg("External · modelled (Open-Meteo)"), kind: "external", hint: msg("Modelled reanalysis or river discharge, not measured at the site.") },
  "external-gbif": { label: msg("External · opportunistic (GBIF)"), kind: "external", hint: msg("Opportunistic occurrence records, not monitoring.") },
  "real-mixed": { label: msg("Real · mixed sources"), kind: "real", hint: msg("Real data from more than one source.") },
  synthetic: { label: msg("Synthetic"), kind: "synthetic", hint: msg("Simulated data. Never real-world performance.") },
};

export function originInfo(origin: string): OriginInfo {
  return (ORIGINS as Record<string, OriginInfo | undefined>)[origin] ?? { label: origin, kind: "synthetic", hint: msg("Unknown origin.") };
}

/** Labels of the data-freshness status; shown with `t()`. */
export const FRESHNESS_LABEL: Record<string, string> = {
  live: msg("Live"),
  snapshot: msg("Snapshot"),
  "snapshot-stale": msg("Stale snapshot"),
  unknown: msg("Freshness unknown"),
};

export const KIND_DOT: Record<OriginInfo["kind"], string> = {
  real: "bg-emerald-600",
  external: "bg-amber-500",
  synthetic: "bg-violet-500",
};

export const KIND_LABEL: Record<OriginInfo["kind"], string> = {
  real: msg("Real data"),
  external: msg("External modelled context"),
  synthetic: msg("Synthetic"),
};

/**
 * Texts that arrive from the service or are built from a code (catalogue titles, parameter statuses, store names): they
 * are listed here so they are extracted for translation, and shown with `t(text)` where they are rendered. A text the
 * list does not know is shown as received (English).
 */
export const DYNAMIC_TEXTS: readonly string[] = [
  msg("Water"), msg("Microbiology"), msg("Context"), msg("Data"), msg("Synthetic labs"),
  msg("Water quality"), msg("Water parameters"), msg("Solids and turbidity"), msg("Organic matter"),
  msg("Bathing classes"), msg("E. coli and enterococci"), msg("Weather"), msg("River discharge"),
  msg("Species nearby"), msg("Data quality"), msg("Citizen science"), msg("Review queue (read-only)"), msg("River risk"),
  msg("sandbox"), msg("EEA Waterbase"), msg("EEA bathing-water classification"), msg("EEA bathing samples"),
  msg("Within limit"), msg("Exceeds limit"), msg("No limit regime"), msg("Unmapped"), msg("Below quantification limit"),
  msg("Good"), msg("Moderate"), msg("Poor"), msg("Unavailable"),
  msg("Loading"), msg("Loading map"), msg("Waiting for the answer"),
];

/** Example questions per index id, shown in the empty state. Plain text only. */
export const SUGGESTIONS: Record<string, string[]> = {
  default: [
    msg("Which water-quality information is available for this country?"),
    msg("How did total phosphorus change between 2017-2024 and 2010-2016?"),
  ],
  "water-quality": [msg("What is the water quality index of the sites in this country?")],
  "water-parameters": [msg("What are the total phosphorus values at a river site?"), msg("How did nitrate change between two periods?")],
  "solids-turbidity": [msg("What are the suspended solids values at a river site?")],
  "organic-matter": [msg("What are the biochemical oxygen demand values at a river site?")],
  "bathing-classes": [msg("How did the bathing-water classes change between two seasons?")],
  "bathing-samples": [msg("How did E. coli concentrations change between 2010-2017 and 2017-2024?")],
  "data-quality": [msg("How many observations were excluded and why?")],
};
