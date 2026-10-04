/** The synthetic labs (a plain module, importable from server and client code). */
export const LAB_IDS = ["citizen-science", "review-queue", "river-risk"] as const;
export type LabId = (typeof LAB_IDS)[number];

export const LAB_TITLES: Record<LabId, string> = {
  "citizen-science": "Citizen science",
  "review-queue": "Review queue (read-only)",
  "river-risk": "River risk",
};
