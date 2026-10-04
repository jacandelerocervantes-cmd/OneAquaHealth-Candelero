"""Evaluation script for split conformal classification on synthetic campaign data."""
from __future__ import annotations

import numpy as np

from oah.paths import qc_report_path
from oah.uncertainty.conformal import (
    RiskCoveragePoint,
    assert_disjoint_specimens,
    compute_calibration_quantile,
    compute_ece,
    compute_posterior_probabilities,
    compute_risk_coverage_curve,
    predict_conformal_set,
)
from oah.synthetic.campaign import generate_campaign
from oah.synthetic.fhir import build_synthetic_batch, rebuild_annotation_table

CALIBRATION_SEEDS = tuple(range(1000, 1030))  # 30 disjoint calibration seeds
TEST_SEEDS = tuple(range(2000, 2030))  # 30 disjoint test seeds
ALPHAS = (0.05, 0.10, 0.20)
SITE_IDS = ("Loc-Almyros", "Loc-Benevento", "Loc-OS")
THRESHOLDS_GRID = tuple(np.linspace(0.0, 1.0, 11))


def run_conformal_evaluation() -> tuple[dict[float, dict[str, float]], list[RiskCoveragePoint]]:
    """Evaluate split conformal prediction across 30 disjoint calibration/test seed pairs."""
    results_by_alpha: dict[float, list[dict[str, float]]] = {alpha: [] for alpha in ALPHAS}
    curve_points_by_threshold: dict[float, list[tuple[float, float]]] = {t: [] for t in THRESHOLDS_GRID}

    for cal_seed, test_seed in zip(CALIBRATION_SEEDS, TEST_SEEDS):
        assert cal_seed != test_seed

        # 1. Calibration Campaign
        cal_camp = generate_campaign(cal_seed, SITE_IDS, observer_count=8, specimens_per_site=70, annotators_per_specimen=5)
        cal_batch = build_synthetic_batch(cal_camp)
        cal_ann = rebuild_annotation_table(cal_batch.records)
        raw_cal_posteriors, _cal_provider = compute_posterior_probabilities(cal_ann, cal_camp.taxa_families)

        cal_true = {f"cal_s{cal_seed}_{spec.specimen_id}": spec.true_family for spec in cal_camp.specimens}
        cal_posteriors = {f"cal_s{cal_seed}_{spec_id}": post for spec_id, post in raw_cal_posteriors.items()}
        cal_scores = [
            1.0 - cal_posteriors[spec_id][true_c]
            for spec_id, true_c in cal_true.items()
        ]

        # 2. Test Campaign (Disjoint Seed)
        test_camp = generate_campaign(test_seed, SITE_IDS, observer_count=8, specimens_per_site=70, annotators_per_specimen=5)

        test_batch = build_synthetic_batch(test_camp)
        test_ann = rebuild_annotation_table(test_batch.records)
        raw_test_posteriors, test_provider = compute_posterior_probabilities(test_ann, test_camp.taxa_families)
        test_true = {f"test_s{test_seed}_{spec.specimen_id}": spec.true_family for spec in test_camp.specimens}
        test_posteriors = {f"test_s{test_seed}_{spec_id}": post for spec_id, post in raw_test_posteriors.items()}

        # 3. Assert calibration and test specimens are strictly disjoint
        assert_disjoint_specimens(cal_true, test_true)

        test_post_list = [test_posteriors[spec_id] for spec_id in test_true.keys()]
        test_true_list = list(test_true.values())

        ece = compute_ece(test_post_list, test_true_list)
        rc_curve = compute_risk_coverage_curve(test_post_list, test_true_list, thresholds=THRESHOLDS_GRID)
        for pt in rc_curve:
            curve_points_by_threshold[pt.threshold].append((pt.coverage, pt.risk))

        for alpha in ALPHAS:
            q_cutoff = compute_calibration_quantile(cal_scores, alpha)
            sets = [
                predict_conformal_set(
                    test_posteriors[spec_id],
                    q_cutoff,
                    provider=test_provider,
                    specimen_id=spec_id,
                )
                for spec_id in test_true.keys()
            ]

            coverages = [
                1.0 if test_true[pset.specimen_id] in pset.prediction_set else 0.0
                for pset in sets
            ]
            set_sizes = [len(pset.prediction_set) for pset in sets]
            singletons = [1.0 if len(pset.prediction_set) == 1 else 0.0 for pset in sets]
            multi_class = [1.0 if len(pset.prediction_set) > 1 else 0.0 for pset in sets]
            empties = [1.0 if len(pset.prediction_set) == 0 else 0.0 for pset in sets]

            results_by_alpha[alpha].append(
                {
                    "coverage": float(np.mean(coverages)),
                    "set_size": float(np.mean(set_sizes)),
                    "singleton_fraction": float(np.mean(singletons)),
                    "multi_fraction": float(np.mean(multi_class)),
                    "empty_fraction": float(np.mean(empties)),
                    "ece": float(ece),
                }
            )

    summary = {}
    for alpha in ALPHAS:
        records = results_by_alpha[alpha]
        summary[alpha] = {
            "coverage_mean": float(np.mean([r["coverage"] for r in records])),
            "coverage_std": float(np.std([r["coverage"] for r in records])),
            "set_size_mean": float(np.mean([r["set_size"] for r in records])),
            "set_size_std": float(np.std([r["set_size"] for r in records])),
            "singleton_mean": float(np.mean([r["singleton_fraction"] for r in records])),
            "multi_mean": float(np.mean([r["multi_fraction"] for r in records])),
            "empty_mean": float(np.mean([r["empty_fraction"] for r in records])),
            "ece_mean": float(np.mean([r["ece"] for r in records])),
        }

    avg_curve = []
    for t in THRESHOLDS_GRID:
        pts = curve_points_by_threshold[t]
        mean_cov = float(np.mean([p[0] for p in pts]))
        mean_risk = float(np.mean([p[1] for p in pts]))
        avg_curve.append(RiskCoveragePoint(float(t), mean_cov, mean_risk))

    return summary, avg_curve


def build_markdown_report(
    summary: dict[float, dict[str, float]],
    risk_coverage_curve: list[RiskCoveragePoint],
) -> str:
    """Generate Markdown report for split conformal prediction evaluation."""
    coverage_notes = []
    for alpha in ALPHAS:
        gap = summary[alpha]["coverage_mean"] - (1.0 - alpha)
        relation = "at or above" if gap >= 0 else "below"
        coverage_notes.append(
            f"alpha = {alpha:.2f}: measured coverage {summary[alpha]['coverage_mean']:.4f} is {relation} "
            f"the target {1.0 - alpha:.2f} (difference {gap:+.4f})."
        )
    lines = [
        "# Split Conformal Prediction Evaluation Report",
        "",
        "> [!IMPORTANT]",
        "> **SYNTHETIC: measures the simulator, not real ecology**",
        "",
        "## Executive Summary",
        "",
        "This evaluation measures the empirical coverage and prediction set efficiency of Split Conformal Prediction for macroinvertebrate family classification.",
        "- Calibration and test datasets are generated from **strictly disjoint seeds** (Calibration: seeds 1000-1029, Test: seeds 2000-2029; $N=30$ seed pairs).",
        *[f"- {note}" for note in coverage_notes],
        "",
        "## Conformal Coverage & Set Efficiency (30 Disjoint Seed Pairs)",
        "",
        "| Target Misclassification (alpha) | Target Coverage (1 - alpha) | Empirical Coverage (Mean ± Std) | Mean Set Size | Singleton Sets (Autonomous) | Multi-Class Sets (To Review) | Empty Sets | ECE (10 Bins) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    for alpha in ALPHAS:
        s = summary[alpha]
        target_cov = 1.0 - alpha
        lines.append(
            f"| **{alpha:.2f}** | {target_cov:.2f} | {s['coverage_mean']:.4f} ± {s['coverage_std']:.4f} | "
            f"{s['set_size_mean']:.2f} | {s['singleton_mean']*100:.1f}% | {s['multi_mean']*100:.1f}% | "
            f"{s['empty_mean']*100:.1f}% | {s['ece_mean']:.4f} |"
        )

    lines.extend(
        [
            "",
            "## Risk-Coverage & Selective Prediction Curve",
            "",
            "- **Autonomous Processing**: Specimens with singleton sets ($|\\mathcal{C}(x)| = 1$) achieve high individual precision and bypass human review.",
            "- **Human-Review Routing**: Non-singleton sets ($|\\mathcal{C}(x)| > 1$ or $|\\mathcal{C}(x)| = 0$) represent ambiguous or low-confidence identifications and are automatically routed to the human review queue.",
            "",
            "| Confidence Threshold (t) | Selective Coverage | Selective Risk (Error Rate) |",
            "| --- | --- | --- |",
        ]
    )

    for pt in risk_coverage_curve:
        lines.append(
            f"| **{pt.threshold:.2f}** | {pt.coverage*100:.1f}% | {pt.risk*100:.2f}% |"
        )

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    """Execute conformal evaluation script, print report, and save Markdown artifact."""
    summary, curve = run_conformal_evaluation()
    report_content = build_markdown_report(summary, curve)

    target_path = qc_report_path("conformal_eval_report.md")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(report_content, encoding="utf-8")

    print(report_content)
    print(f"\nReport written to: {target_path}")


if __name__ == "__main__":
    main()
