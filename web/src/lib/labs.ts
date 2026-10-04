import { msg } from "./i18n-core";

/** The synthetic labs (a plain module, importable from server and client code). Titles are shown through `t()`. */
export const LAB_IDS = ["citizen-science", "review-queue", "river-risk"] as const;
export type LabId = (typeof LAB_IDS)[number];

export const LAB_TITLES: Record<LabId, string> = {
  "citizen-science": msg("Citizen science"),
  "review-queue": msg("Review queue (read-only)"),
  "river-risk": msg("River risk"),
};
