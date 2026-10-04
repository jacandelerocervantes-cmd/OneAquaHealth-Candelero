"""Validate real fixtures and a balanced sandbox sample with the official validator."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path
from oah.fhir.official_validator import validate
from oah.fhir.validation_report import (
    build_markdown_report,
    build_report,
    select_validation_sample,
)
from oah.ingest.sandbox_client import configured_client
from oah.paths import fixtures_real_path, ig_build_path, qc_report_path

def main() -> None:
    fixtures = [file for file in fixtures_real_path().glob("*.json") if not file.name.endswith(".metadata.json")]
    observations = [item for page in configured_client().pages("Observation") for item in page]
    selected = select_validation_sample(observations)
    with tempfile.TemporaryDirectory() as temporary:
        sample_files = []
        for index, resource in enumerate(selected):
            file = Path(temporary).joinpath(f"observation-{index:02d}.json")
            file.write_text(json.dumps(resource, sort_keys=True), encoding="utf-8")
            sample_files.append(file)
        output = qc_report_path("official-validator-output.json")
        issues = validate(fixtures + sample_files, ig_build_path("fsh-generated", "resources"), output)
    profiles = [profile for resource in selected for profile in resource.get("meta", {}).get("profile", [])]
    report = build_report(issues, profiles)
    target = qc_report_path("official-validation-report.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_markdown_report(report), encoding="utf-8")
    print(target)
    print(report["severity_counts"])
    if any(level in report["severity_counts"] for level in ("fatal", "error")):
        raise SystemExit(1)

if __name__ == "__main__":
    main()
