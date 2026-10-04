import type { ChatResponse } from "./api";

/** The fixed notice shown on every screen. It is a constant of the app, never model output. */
export const FIXED_NOTICE =
  "Screening against reference values, not legal compliance. No health or safety verdicts. AI answers are generated from tool results and are not verified.";

export const FALLBACK_DISCLAIMER =
  "AI-generated from tool results, not verified. Screening against reference values, not legal compliance; never a potability, health or regulatory determination.";

export const DEFAULT_LANGUAGE = "es-MX";
export const DEFAULT_COUNTRY = "GR";
export const SOURCE_LANGUAGE = "en";
export const MAX_MESSAGE_LENGTH = 500;
export const MAX_HISTORY_TURNS = 6;

export const COUNTRY_NAMES: Record<string, string> = { GR: "Greece", IT: "Italy", NO: "Norway" };

export const USER_LABEL = "Judge account";

type Origin = ChatResponse["origin"];

export interface OriginInfo {
  label: string;
  kind: "real" | "external" | "synthetic";
  hint: string;
}

/** Labels for every origin value of the contract; real, external and synthetic never share a label. */
export const ORIGINS: Record<Origin, OriginInfo> = {
  "real-sandbox": { label: "Real · HL7 Europe sandbox", kind: "real", hint: "Real data from the HL7 Europe sandbox." },
  "real-eea-waterbase": { label: "Real · EEA Waterbase", kind: "real", hint: "Real data from the EEA Waterbase 2026 store." },
  "real-eea-bathing-water": { label: "Real · EEA bathing water", kind: "real", hint: "Real classification from the EEA Bathing Water Directive data." },
  "real-eea-bathing-samples": { label: "Real · EEA bathing samples", kind: "real", hint: "Real monitoring results from the EEA Discodata bathing-water table." },
  "external-open-meteo": { label: "External · modelled (Open-Meteo)", kind: "external", hint: "Modelled reanalysis or river discharge, not measured at the site." },
  "external-gbif": { label: "External · opportunistic (GBIF)", kind: "external", hint: "Opportunistic occurrence records, not monitoring." },
  "real-mixed": { label: "Real · mixed sources", kind: "real", hint: "Real data from more than one source." },
  synthetic: { label: "Synthetic", kind: "synthetic", hint: "Simulated data. Never real-world performance." },
};

export function originInfo(origin: string): OriginInfo {
  return (ORIGINS as Record<string, OriginInfo | undefined>)[origin] ?? { label: origin, kind: "synthetic", hint: "Unknown origin." };
}

export const KIND_DOT: Record<OriginInfo["kind"], string> = {
  real: "bg-emerald-600",
  external: "bg-amber-500",
  synthetic: "bg-violet-500",
};

export const KIND_LABEL: Record<OriginInfo["kind"], string> = {
  real: "Real data",
  external: "External modelled context",
  synthetic: "Synthetic",
};

/** Example questions per index id, shown in the empty state. Plain text only. */
export const SUGGESTIONS: Record<string, string[]> = {
  default: ["Which water-quality information is available for this country?", "How did total phosphorus change between 2017-2024 and 2010-2016?"],
  "water-quality": ["What is the water quality index of the sites in this country?"],
  "water-parameters": ["What are the total phosphorus values at a river site?", "How did nitrate change between two periods?"],
  "solids-turbidity": ["What are the suspended solids values at a river site?"],
  "organic-matter": ["What are the biochemical oxygen demand values at a river site?"],
  "bathing-classes": ["How did the bathing-water classes change between two seasons?"],
  "bathing-samples": ["How did E. coli concentrations change between 2010-2017 and 2017-2024?"],
  "data-quality": ["How many observations were excluded and why?"],
};
