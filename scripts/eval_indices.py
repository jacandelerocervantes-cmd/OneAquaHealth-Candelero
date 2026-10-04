"""Evaluation script for ecological and water quality indices on real sandbox data."""

from __future__ import annotations

from oah.indices.apply_to_sandbox import apply_ccme_wqi_to_sandbox
from oah.paths import qc_report_path


def build_markdown_report(results: dict) -> str:
    """Generate Markdown report summarizing real-sandbox CCME WQI evaluation."""
    lines = [
        "# Ecological and Water Quality Indices Evaluation Report",
        "",
        "> [!IMPORTANT]",
        f"> **{results.get('input_origin', 'real-sandbox')}**",
        "",
        "## Executive Summary",
        "",
        "This evaluation calculates physicochemical water quality indices on real FHIR sandbox data per location.",
        f"- Analyzed **{results['total_observations_analyzed']}** real sandbox observations across **{results['total_locations_found']}** distinct location references.",
        f"- Skipped **{results['skipped_health_measure_observations']}** population health measure observations (`observation-health-measure-oah`) that do not contain aquatic environmental data.",
        f"- Skipped **{results['skipped_unmapped_code_observations']}** unmapped/non-physicochemical observations.",
        f"- Evaluated **{results['evaluated_locations_count']}** locations with valid physicochemical measurements.",
        f"- Skipped **{results['skipped_locations_count']}** locations lacking evaluable physicochemical observations.",
        "",
        "## Objective Limits Source Attribution",
        "",
        f"> {results['objective_limits_source']}",
        "",
        "## Real Sandbox CCME WQI Evaluation",
        "",
        "| Location Reference | Total Observations | Distinct Parameters | Evaluable Measurements | Failed Measurements | CCME WQI (0-100) | Confidence Status |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]

    for loc in results.get("evaluated_locations", []):
        conf_str = "Normal" if loc["confidence"] == "normal" else "Low Confidence (< 4 variables)"
        lines.append(
            f"| **{loc['location_ref']}** | {loc['total_observations']} | "
            f"{loc['distinct_parameters_count']} | {loc['evaluable_measurements']} | "
            f"{loc['failed_measurements']} | {loc['ccme_wqi']:.2f} | {conf_str} |"
        )

    lines.extend(
        [
            "",
            "## Skipped Locations & Documented Reasons",
            "",
            "| Location Reference | Total Observations | Documented Reason |",
            "| --- | --- | --- |",
        ]
    )

    for loc in results.get("skipped_locations", []):
        lines.append(
            f"| **{loc['location_ref']}** | {loc['total_observations']} | {loc['reason']} |"
        )

    lines.extend(
        [
            "",
            "## Macroinvertebrate & Diversity Indices Notice",
            "",
            f"> {results['macroinvertebrate_indices_note']}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    """Execute indices evaluation on sandbox data and write Markdown report."""
    results = apply_ccme_wqi_to_sandbox()
    report_content = build_markdown_report(results)

    target_path = qc_report_path("indices_report.md")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(report_content, encoding="utf-8")

    print(report_content)
    print(f"\nReport written to: {target_path}")


if __name__ == "__main__":
    main()
