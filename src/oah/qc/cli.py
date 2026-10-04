"""Command-line QC report generation."""
import json
from oah.ingest.sandbox_client import configured_client
from oah.paths import qc_report_path
from oah.qc.report import build_report
def main():
    observations = [item for page in configured_client().pages("Observation") for item in page]
    report = build_report(observations, default_origin="real-sandbox")
    target = qc_report_path("observations.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown = target.with_suffix(".md")
    lines = ["# OAH Observation QC report", "", f"Generated: {report['generated_at_utc']}", f"Source: {report['source']}", f"Origin: {report['origin']}", f"Total observations: {report['total_observations']}", "", "## Profiles", "", "| Profile | Count |", "| --- | ---: |"]
    lines.extend(f"| {key} | {value} |" for key, value in sorted(report["profiles"].items()))
    lines.extend(["", "## Observation origin", "", "| Classification | Count |", "| --- | ---: |"])
    lines.extend(f"| {key} | {value} |" for key, value in report["observation_origin_counts"].items())
    lines.extend(["", "Health-measure and indicators profiles receive no OAH profile check yet.", "", "## Findings", "", "| Code | Count |", "| --- | ---: |"])
    lines.extend(f"| {key} | {value} |" for key, value in sorted(report["findings"].items()))
    lines.extend(["", "## Top sites", ""])
    lines.extend(f"- {key}: {value}" for key, value in sorted(report["sites"].items(), key=lambda item: item[1], reverse=True)[:5])
    lines.extend(["", f"Quantity values without code: {report['quantity_values_without_code']}", f"Codes seen: {', '.join(report['quantity_codes'])}", f"pH review count: {report['pH_code_to_review']} (pH vs [pH] is unverified)", "", "## Examples", ""])
    lines.extend(f"- {key}: {', '.join(value['ids'][:5])}" for key, value in sorted(report["examples"].items()))
    markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(target)
    print(markdown)
    print(report["total_observations"])
    print(report["findings"])
