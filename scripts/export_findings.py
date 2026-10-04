"""Export deterministic FHIR QC findings from real sandbox Observations."""
from __future__ import annotations

import json

from oah.config import sandbox_url
from oah.fhir.output.export import build_findings_bundle
from oah.ingest.sandbox_client import configured_client
from oah.paths import export_path
from oah.timeutil import format_utc, utc_now


def main() -> None:
    observations = [item for page in configured_client().pages("Observation") for item in page]
    retrieval_date = format_utc(utc_now())
    findings_bundle = build_findings_bundle(observations, retrieval_date, sandbox_url(), default_origin="real-sandbox")
    target = export_path("findings-bundle.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(findings_bundle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    resources = [entry["resource"] for entry in findings_bundle["entry"]]
    issue_count = sum(resource["resourceType"] == "DetectedIssue" for resource in resources)
    print(f"Observations: {len(observations)}")
    print("Input origin: real-sandbox")
    print(f"DetectedIssue findings: {issue_count}")
    print("Device: 1")
    print("Provenance: 1")
    print("Bundle: 1")
    print(target)


if __name__ == "__main__":
    main()
