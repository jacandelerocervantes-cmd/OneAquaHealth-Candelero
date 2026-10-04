import { MOCK_AS_OF, freshness, siteById } from "../data";
import { type MockResult, ok, NO_SITE } from "../common";
import type { Schema } from "@/lib/api";

export function qc(): MockResult {
  const body: Schema<"QcReportResponse"> = {
    origin: "synthetic",
    data_freshness: freshness,
    generated_at_utc: MOCK_AS_OF,
    source: "mock",
    total_observations: 1200,
    findings: { "missing-unit": 4, "implausible-value": 7, "duplicate-observation": 2 },
    excluded_observations: { "official-record-filter": 12 },
    excluded_observations_total: 12,
  };
  return ok(body);
}

export function reliability(p: URLSearchParams): MockResult {
  const seed = Number(p.get("seed") ?? 1) || 1;
  const body: Schema<"ReliabilityCampaignResponse"> = {
    origin: "synthetic",
    seed,
    recommended_method: "dawid-skene",
    recommendation_diagnostics: { note: "mock" },
    parameters: { observers: 8, specimens_per_site: 40, annotators_per_specimen: 3 },
    majority_vote_accuracy: 0.81,
    dawid_skene_accuracy: 0.88,
    majority_vote_macro_f1: 0.79,
    dawid_skene_macro_f1: 0.86,
    dawid_skene_log_loss: 0.41,
  };
  return ok(body);
}

export function reviewQueue(): MockResult {
  const body: Schema<"ReviewQueueResponse"> = {
    origin: "synthetic",
    count: 3,
    items: [
      { specimen_id: "mock-spec-001", status: "pending", tag: "synthetic", prediction_set: ["A", "B"], probabilities: { A: 0.55, B: 0.4, C: 0.05 } },
      { specimen_id: "mock-spec-002", status: "pending", tag: "synthetic", prediction_set: ["C"], probabilities: { A: 0.05, B: 0.1, C: 0.85 } },
      { specimen_id: "mock-spec-003", status: "pending", tag: "synthetic", prediction_set: ["A", "C"], probabilities: { A: 0.48, B: 0.04, C: 0.48 } },
    ],
  };
  return ok(body);
}

export function risk(id: string): MockResult {
  if (!siteById(id)) return NO_SITE(id);
  const body: Schema<"RiskResponse"> = {
    origin: "synthetic",
    site_id: id,
    source_site: id,
    risk: 0.23,
    note: "Synthetic river-risk score for the interface demo; not a prediction for a real river.",
  };
  return ok(body);
}
