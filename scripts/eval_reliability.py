"""Script to evaluate Dawid-Skene observer reliability across data-poor and data-rich regimes."""
from __future__ import annotations

from oah.paths import qc_report_path
from oah.reliability.dawid_skene import recommend_method
from oah.reliability.eval import run_regime_experiment
from oah.synthetic.campaign import generate_campaign
from oah.synthetic.fhir import build_synthetic_batch, rebuild_annotation_table

SEEDS = tuple(range(42, 52))  # 10 test seeds: 42..51
HELD_OUT_SEEDS = tuple(range(100, 110))  # 10 held-out tuning seeds: 100..109
FRESH_SEEDS = tuple(range(200, 230))  # 30 fresh evaluation seeds: 200..229
SITE_IDS = ("Loc-Almyros", "Loc-Benevento", "Loc-OS")
OBSERVER_COUNT = 8
SMOOTHING = 1.0
RECOMMENDATION_THRESHOLD = 50.0
WIN_RATE_TARGET = 0.8
REGIMES = (("15x3", 15, 3), ("15x5", 15, 5), ("70x3", 70, 3), ("70x5", 70, 5))


def run_threshold_grid() -> list[dict]:
    """Measure every regime on the three disjoint seed sets; nothing in the report is typed by hand."""
    rows = []
    for name, per_site, annotators in REGIMES:
        wins = {}
        for label, seeds in (("held_out", HELD_OUT_SEEDS), ("test", SEEDS), ("fresh", FRESH_SEEDS)):
            summary = run_regime_experiment(
                seeds=seeds,
                site_ids=SITE_IDS,
                observer_count=OBSERVER_COUNT,
                specimens_per_site=per_site,
                annotators_per_specimen=annotators,
                smoothing=SMOOTHING,
            )
            wins[label] = summary["ds_win_fraction"]
        campaign = generate_campaign(42, SITE_IDS, OBSERVER_COUNT, per_site, annotators)
        annotations = rebuild_annotation_table(build_synthetic_batch(campaign).records)
        recommended, diagnostics = recommend_method(annotations, threshold=RECOMMENDATION_THRESHOLD)
        rows.append(
            {
                "regime": name,
                "specimens_per_site": per_site,
                "annotators": annotators,
                "ann_per_obs": diagnostics["mean_annotations_per_observer"],
                "recommended": recommended,
                **wins,
            }
        )
    return rows


def run_evaluation() -> dict[str, dict]:
    """Run evaluation across data-poor and data-rich regimes over test seeds 42..51."""
    poor_summary = run_regime_experiment(
        seeds=SEEDS,
        site_ids=SITE_IDS,
        observer_count=OBSERVER_COUNT,
        specimens_per_site=15,
        annotators_per_specimen=3,
        smoothing=SMOOTHING,
    )
    rich_summary = run_regime_experiment(
        seeds=SEEDS,
        site_ids=SITE_IDS,
        observer_count=OBSERVER_COUNT,
        specimens_per_site=70,
        annotators_per_specimen=5,
        smoothing=SMOOTHING,
    )

    # Get sample annotations for recommendation check
    poor_camp = generate_campaign(42, SITE_IDS, OBSERVER_COUNT, 15, 3)
    poor_ann = rebuild_annotation_table(build_synthetic_batch(poor_camp).records)
    poor_rec, poor_diag = recommend_method(poor_ann, threshold=RECOMMENDATION_THRESHOLD)

    rich_camp = generate_campaign(42, SITE_IDS, OBSERVER_COUNT, 70, 5)
    rich_ann = rebuild_annotation_table(build_synthetic_batch(rich_camp).records)
    rich_rec, rich_diag = recommend_method(rich_ann, threshold=RECOMMENDATION_THRESHOLD)

    poor_summary["recommendation"] = poor_rec
    poor_summary["diagnostics"] = poor_diag
    rich_summary["recommendation"] = rich_rec
    rich_summary["diagnostics"] = rich_diag

    return {
        "data-poor": poor_summary,
        "data-rich": rich_summary,
        "grid": {"rows": run_threshold_grid()},
    }


def _threshold_paragraph(rows: list[dict]) -> str:
    """State what the measured grid supports about the configured threshold, and what it does not."""
    meeting = [row for row in rows if row["held_out"] >= WIN_RATE_TARGET]
    if meeting:
        lowest = min(meeting, key=lambda row: row["ann_per_obs"])
        found = (
            f"Among the four regimes measured, the lowest volume with a held-out win rate of at least "
            f"{WIN_RATE_TARGET:.0%} was **{lowest['regime']}** (~{lowest['ann_per_obs']:.1f} annotations per observer)."
        )
    else:
        found = f"No measured regime reached a held-out win rate of {WIN_RATE_TARGET:.0%}."
    return (
        f"{found} Only four regimes were measured, so the configured threshold of "
        f"**{RECOMMENDATION_THRESHOLD:.0f} annotations per observer** is a project choice inside an unmeasured "
        "gap, not a measured minimum."
    )


def _grid_table(rows: list[dict]) -> list[str]:
    lines = [
        "| Regime | Specimens/Site | Annotators | Ann/Obs | Held-Out Win Rate (100-109) | Eval Win Rate (42-51) | Eval Win Rate (200-229) | Recommended Method |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| **{row['regime']}** | {row['specimens_per_site']} | {row['annotators']} | ~{row['ann_per_obs']:.1f} | "
            f"{row['held_out'] * 100:.0f}% | {row['test'] * 100:.0f}% | {row['fresh'] * 100:.0f}% | `{row['recommended']}` |"
        )
    return lines


def build_markdown_report(results: dict[str, dict]) -> str:
    """Generate Markdown report content detailing regime performance."""
    poor = results["data-poor"]
    rich = results["data-rich"]

    lines = [
        "# Observer Reliability Evaluation Report: Dawid-Skene vs Majority Vote",
        "",
        "> [!IMPORTANT]",
        "> **SYNTHETIC: measures the simulator, not real ecology**",
        "",
        "## Executive Summary",
        "",
        "This evaluation compares Dawid-Skene with Majority Vote on simulated campaigns; every figure below is computed by this run.",
        f"- **Data-poor** (15 specimens/site, 3 annotators, ~{poor['diagnostics']['mean_annotations_per_observer']:.1f} ann/obs): Dawid-Skene beat Majority Vote in {poor['ds_win_fraction'] * 100:.0f}% of the {len(SEEDS)} test seeds.",
        f"- **Data-rich** (70 specimens/site, 5 annotators, ~{rich['diagnostics']['mean_annotations_per_observer']:.1f} ann/obs): Dawid-Skene beat Majority Vote in {rich['ds_win_fraction'] * 100:.0f}% of the {len(SEEDS)} test seeds.",
        "- These are simulator results; they support no claim about real observers.",
        "",
        "## Threshold Evaluation Grid",
        "",
        _threshold_paragraph(results["grid"]["rows"]),
        "",
        *_grid_table(results["grid"]["rows"]),
        "",
        "## Side-by-Side Regime Comparison (Test Seeds 42-51, $N=10$)",
        "",
        "| Metric | Data-Poor Regime (15 spec/site, 3 ann) | Data-Rich Regime (70 spec/site, 5 ann) |",
        "| --- | --- | --- |",
        f"| **Recommended Method** | `{poor['recommendation']}` | `{rich['recommendation']}` |",
        f"| **Majority Vote Accuracy** | {poor['mv_accuracy']['mean']:.4f} ± {poor['mv_accuracy']['std']:.4f} | {rich['mv_accuracy']['mean']:.4f} ± {rich['mv_accuracy']['std']:.4f} |",
        f"| **Dawid-Skene Accuracy** | {poor['ds_accuracy']['mean']:.4f} ± {poor['ds_accuracy']['std']:.4f} | {rich['ds_accuracy']['mean']:.4f} ± {rich['ds_accuracy']['std']:.4f} |",
        f"| **DS Win Rate (DS > MV)** | {poor['ds_win_fraction'] * 100:.1f}% ({int(poor['ds_win_fraction'] * len(SEEDS))}/{len(SEEDS)} seeds) | {rich['ds_win_fraction'] * 100:.1f}% ({int(rich['ds_win_fraction'] * len(SEEDS))}/{len(SEEDS)} seeds) |",
        f"| **Majority Vote Macro F1** | {poor['mv_macro_f1']['mean']:.4f} ± {poor['mv_macro_f1']['std']:.4f} | {rich['mv_macro_f1']['mean']:.4f} ± {rich['mv_macro_f1']['std']:.4f} |",
        f"| **Dawid-Skene Macro F1** | {poor['ds_macro_f1']['mean']:.4f} ± {poor['ds_macro_f1']['std']:.4f} | {rich['ds_macro_f1']['mean']:.4f} ± {rich['ds_macro_f1']['std']:.4f} |",
        f"| **Dawid-Skene Log Loss** | {poor['log_loss']['mean']:.4f} ± {poor['log_loss']['std']:.4f} | {rich['log_loss']['mean']:.4f} ± {rich['log_loss']['std']:.4f} |",
        f"| **Mean Frobenius Distance** | {poor['mean_frobenius_distance']['mean']:.4f} ± {poor['mean_frobenius_distance']['std']:.4f} | {rich['mean_frobenius_distance']['mean']:.4f} ± {rich['mean_frobenius_distance']['std']:.4f} |",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    """Execute regime comparison evaluation, print report, and save Markdown artifact."""
    results = run_evaluation()
    report_content = build_markdown_report(results)

    target_path = qc_report_path("reliability_eval_report.md")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(report_content, encoding="utf-8")

    print(report_content)
    print(f"\nReport written to: {target_path}")


if __name__ == "__main__":
    main()
