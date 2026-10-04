"""Manual, real-API evaluation of the grounded LLM explanation layer (oah.explain).

Unlike the rest of this project's test suite, this script makes real Anthropic API calls and
costs real money to run. It is never invoked by pytest or scripts/run_pipeline.py; run it by
hand to verify the explanation layer end to end, the same pattern already used for
scripts/validate_official.py against the real HL7 validator. If ANTHROPIC_API_KEY is not
configured, this script prints why and exits without making any request.

Evidence sources, both already computed by other, already-tested oah.* modules -- this script
adds no new business logic:
  1. One real-sandbox Location's CCME WQI result (oah.indices.apply_to_sandbox).
  2. One synthetic, non-singleton conformal prediction set from a small demo campaign
     (oah.synthetic + oah.uncertainty.conformal) -- shaped exactly like a real human-review
     queue item, without needing a populated ReviewStore.

Each evidence source is called twice, once per oah.explain mode ("describe", the strictly
factual restatement, and "assess", the interpretive concern-level + recommendation reading) --
four real API calls total per run.
"""
from __future__ import annotations

from typing import Any

from oah.explain import LLMNotConfiguredError, LLMRequestError, build_client, explain
from oah.explain.prompts import Mode
from oah.indices.apply_to_sandbox import apply_ccme_wqi_to_sandbox, data_quality, limits_note
from oah.paths import qc_report_path
from oah.synthetic.campaign import generate_campaign
from oah.synthetic.fhir import build_synthetic_batch, rebuild_annotation_table
from oah.uncertainty.conformal import compute_calibration_quantile, compute_posterior_probabilities, predict_conformal_set

DEMO_SEED = 4242
DEMO_SITE_IDS = ("Loc-Almyros", "Loc-Benevento", "Loc-OS")


_MODES: tuple[Mode, ...] = ("describe", "assess")


def _first_evaluated_wqi_location() -> dict[str, Any] | None:
    results = apply_ccme_wqi_to_sandbox()  # live sandbox, or the local snapshot when it is unreachable
    evaluated = results["evaluated_locations"]
    if not evaluated:
        return None
    return {
        "origin": "real-sandbox",
        "status": "evaluated",
        **evaluated[0],
        "data_quality": data_quality(results),
        "objective_limits_source": limits_note(results),
    }


def _one_non_singleton_review_evidence() -> dict[str, Any] | None:
    campaign = generate_campaign(
        DEMO_SEED, DEMO_SITE_IDS, observer_count=6, specimens_per_site=10, annotators_per_specimen=2
    )
    batch = build_synthetic_batch(campaign)
    annotations = rebuild_annotation_table(batch.records)
    posteriors, provider = compute_posterior_probabilities(annotations, campaign.taxa_families)

    calibration_scores = [
        1.0 - posteriors[specimen.specimen_id][specimen.true_family]
        for specimen in campaign.specimens
        if specimen.specimen_id in posteriors
    ]
    cutoff = compute_calibration_quantile(calibration_scores, alpha=0.10)

    for specimen in campaign.specimens:
        if specimen.specimen_id not in posteriors:
            continue
        prediction = predict_conformal_set(
            posteriors[specimen.specimen_id], cutoff, provider=provider, specimen_id=specimen.specimen_id
        )
        if len(prediction.prediction_set) > 1:
            return {
                "specimen_id": prediction.specimen_id,
                "prediction_set": list(prediction.prediction_set),
                "probabilities": prediction.probabilities,
                "status": "pending",
                "tag": "synthetic",
            }
    return None


def build_report(sections: list[tuple[str, dict[str, Any], Any]]) -> str:
    lines = [
        "# LLM Explanation Layer -- Real-API Evaluation Report",
        "",
        "> [!IMPORTANT]",
        "> This report was produced by real calls to the Anthropic API (oah.explain), run",
        "> manually. It is not part of the automated test suite or scripts/run_pipeline.py.",
        "",
    ]
    for title, evidence, result in sections:
        lines.append(f"## {title} (mode={result.mode})")
        lines.append("")
        lines.append(f"- Origin: `{evidence.get('origin', evidence.get('tag', 'unknown'))}`")
        lines.append(f"- Model: `{result.model}`")
        if result.input_tokens is not None:
            lines.append(f"- Tokens: {result.input_tokens} in, {result.output_tokens} out")
        lines.append(f"- Grounded: **{result.grounded}**" + (f" (ungrounded: {result.ungrounded_numbers})" if not result.grounded else ""))
        lines.append("")
        lines.append(f"> {result.text}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    try:
        client = build_client()
    except LLMNotConfiguredError as error:
        print(f"Skipped: {error}")
        return

    sections = []

    location_evidence = _first_evaluated_wqi_location()
    if location_evidence is not None:
        for mode in _MODES:
            try:
                result = explain("ccme-wqi-location", location_evidence, client=client, mode=mode)
            except LLMRequestError as error:
                print(f"Real API call failed (mode={mode}): {error.detail}")
                continue
            sections.append(("Real-sandbox CCME WQI location", location_evidence, result))
    else:
        print("No evaluated real-sandbox WQI location available this run; skipping that evidence.")

    review_evidence = _one_non_singleton_review_evidence()
    if review_evidence is not None:
        for mode in _MODES:
            try:
                result = explain("review-queue-item", review_evidence, client=client, mode=mode)
            except LLMRequestError as error:
                print(f"Real API call failed (mode={mode}): {error.detail}")
                continue
            sections.append(("Synthetic review-queue item", review_evidence, result))
    else:
        print(f"No non-singleton specimen found for seed {DEMO_SEED} this run; skipping that evidence.")

    if not sections:
        print("Nothing to report.")
        return

    report = build_report(sections)
    target = qc_report_path("explain_eval_report.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report, encoding="utf-8")

    print(report)
    print(f"\nReport written to: {target}")


if __name__ == "__main__":
    main()
