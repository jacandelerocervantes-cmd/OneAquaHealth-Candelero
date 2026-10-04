"""Validate EVERY real sandbox resource (all types) with the official HL7 validator against the built IG."""
from __future__ import annotations

import json
import tempfile
from collections import Counter
from pathlib import Path

from oah.fhir.official_validator import validate
from oah.fhir.validation_report import distinct_warning_error_messages, severity_counts
from oah.ingest.sandbox_client import configured_client
from oah.paths import ig_build_path, qc_report_path

BATCH = 60
RESOURCE_TYPES = ("Observation", "Location", "Group", "Library", "Specimen", "Organization")


def main() -> None:
    client = configured_client()
    with tempfile.TemporaryDirectory() as temporary:
        files: list[Path] = []
        per_type: Counter[str] = Counter()
        for resource_type in RESOURCE_TYPES:
            for page in client.pages(resource_type):
                for resource in page:
                    file = Path(temporary).joinpath(f"{resource_type}-{resource['id']}.json")
                    file.write_text(json.dumps(resource, sort_keys=True), encoding="utf-8")
                    files.append(file)
                    per_type[resource_type] += 1
        issues = []
        for start in range(0, len(files), BATCH):  # Windows caps the command line length
            output = qc_report_path(f"all-real-validator-output-{start // BATCH:02d}.json")
            issues += validate(files[start : start + BATCH], ig_build_path("fsh-generated", "resources"), output, timeout=1800)
    counts = severity_counts(issues)
    lines = ["# Official validation of all real sandbox resources", "", f"Resources validated: {dict(per_type)}", f"Severity counts: {counts}", ""]
    lines += [f"- {severity} [{code}]: {message}" for severity, code, message in distinct_warning_error_messages(issues)]
    target = qc_report_path("all-real-validation-report.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(dict(per_type), counts)
    print(target)
    if any(level in counts for level in ("fatal", "error")):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
