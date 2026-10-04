"""One-command end-to-end pipeline over the real OneAquaHealth sandbox.

Stages, in order: sandbox snapshot -> QC report -> FHIR R4B structural validation ->
FHIR export with Provenance -> ecological indices -> synthetic river-network risk demo.

Every stage writes its own output under the configured data directory; nothing is written
inside the repository. Each mandatory stage's core function is the same already-tested
oah.* function used elsewhere in the project -- this script adds no new business logic, only
sequencing and reporting.

Failure policy: a mandatory stage that raises stops the whole run immediately with a clear,
specific error naming the stage and the original exception; nothing downstream runs on a
false summary. The one OPTIONAL stage (validation against the official HL7 validator) needs
external tools (Java, the validator jar, a built Implementation Guide) that may not be present
in a given environment; if any prerequisite is missing, that single stage is explicitly
reported as SKIPPED with the exact missing prerequisite named -- it is never silently omitted.
"""
from __future__ import annotations

import shutil
import sys
from typing import Any

from oah.fhir.output.export import build_findings_bundle
from oah.fhir.validate import validate_resource
from oah.indices.apply_to_sandbox import apply_ccme_wqi_to_sandbox
from oah.indices.sandbox_loader import fetch_sandbox_observations
from oah.ingest.sandbox_client import configured_client
from oah.paths import export_path, ig_build_path, qc_report_path, tools_dir
from oah.qc.report import build_report
from oah.risk import (
    DECAY_PER_KM,
    INITIAL_RISK,
    SOURCE_SITE,
    SYNTHETIC_EDGES,
    build_river_graph,
    propagate_risk,
)
from oah.timeutil import format_utc, utc_now


class StageFailure(RuntimeError):
    """Raised to stop the pipeline with a clear, stage-specific message."""


def _write_json(path, payload) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def stage_snapshot() -> list[dict[str, Any]]:
    print("[1/6] Sandbox snapshot ...", flush=True)
    try:
        client = configured_client()
        snapshot_path = client.snapshot("Observation")
    except Exception as error:  # noqa: BLE001 - re-raised with stage context below
        raise StageFailure(f"snapshot stage failed while fetching the live sandbox: {error}") from error
    observations = fetch_sandbox_observations()
    if not observations:
        raise StageFailure("snapshot stage produced zero Observations; refusing to continue.")
    print(f"      wrote {snapshot_path} ({len(observations)} Observations)")
    return observations


def stage_qc(observations: list[dict[str, Any]]) -> dict[str, Any]:
    print("[2/6] QC report ...", flush=True)
    try:
        report = build_report(observations, default_origin="real-sandbox")
    except Exception as error:  # noqa: BLE001
        raise StageFailure(f"QC stage failed: {error}") from error
    target = qc_report_path("pipeline_qc_report.json")
    _write_json(target, report)
    print(f"      wrote {target} (findings: {report['findings']})")
    return report


def stage_structural_validation(observations: list[dict[str, Any]]) -> dict[str, Any]:
    print("[3/6] FHIR R4B structural validation ...", flush=True)
    try:
        results = [validate_resource(observation) for observation in observations]
    except Exception as error:  # noqa: BLE001
        raise StageFailure(f"structural validation stage failed: {error}") from error
    resources_with_findings = sum(1 for result in results if result.findings)
    summary = {
        "origin": "real-sandbox",
        "resources_checked": len(results),
        "resources_with_findings": resources_with_findings,
    }
    target = qc_report_path("pipeline_structural_validation.json")
    _write_json(target, summary)
    print(f"      wrote {target} ({resources_with_findings}/{len(results)} with findings)")
    return summary


def stage_official_validation(observations: list[dict[str, Any]]) -> dict[str, Any]:
    print("[4/6] Official HL7 validator (optional) ...", flush=True)
    missing = []
    if not shutil.which("java"):
        missing.append("Java executable not found on PATH")
    jar = tools_dir() / "validator_cli.jar"
    if not jar.is_file():
        missing.append(f"validator jar not found (expected at the configured tools directory: {jar.name})")
    ig_resources = ig_build_path("fsh-generated", "resources")
    if not ig_resources.is_dir():
        missing.append("built Implementation Guide not found; run scripts/build_ig.py first")

    if missing:
        for reason in missing:
            print(f"      SKIPPED: {reason}")
        return {"origin": "real-sandbox", "status": "skipped", "reasons": missing}

    import tempfile
    from pathlib import Path

    from oah.fhir.official_validator import validate

    sample = observations[:20]
    with tempfile.TemporaryDirectory() as temp_dir:
        files = []
        for resource in sample:
            file_path = Path(temp_dir) / f"{resource['id']}.json"
            _write_json(file_path, resource)
            files.append(file_path)
        try:
            issues = validate(files, ig_resources, Path(temp_dir) / "validator-output.json")
        except Exception as error:  # noqa: BLE001
            raise StageFailure(f"official validation stage failed: {error}") from error

    from collections import Counter

    severity_counts = dict(Counter(issue.severity for issue in issues))
    print(f"      validated {len(sample)} resources; severities: {severity_counts}")
    return {"origin": "real-sandbox", "status": "ran", "sample_size": len(sample), "severity_counts": severity_counts}


def stage_fhir_export(observations: list[dict[str, Any]]) -> dict[str, Any]:
    print("[5/6] FHIR export with Provenance ...", flush=True)
    try:
        from oah.config import sandbox_url

        retrieval_date = format_utc(utc_now())
        bundle = build_findings_bundle(observations, retrieval_date, sandbox_url(), default_origin="real-sandbox")
    except Exception as error:  # noqa: BLE001
        raise StageFailure(f"FHIR export stage failed: {error}") from error

    target = export_path("pipeline-findings-bundle.json")
    _write_json(target, bundle)
    resources = [entry["resource"] for entry in bundle["entry"]]
    issue_count = sum(resource["resourceType"] == "DetectedIssue" for resource in resources)
    print(f"      wrote {target} ({issue_count} DetectedIssue resources)")
    return {"origin": "real-sandbox", "bundle_id": bundle["id"], "detected_issue_count": issue_count}


def stage_indices(observations: list[dict[str, Any]]) -> dict[str, Any]:
    print("[6/6a] Ecological indices ...", flush=True)
    try:
        results = apply_ccme_wqi_to_sandbox(observations)
    except Exception as error:  # noqa: BLE001
        raise StageFailure(f"indices stage failed: {error}") from error
    target = qc_report_path("pipeline_indices_report.json")
    _write_json(target, results)
    print(f"      wrote {target} ({results['evaluated_locations_count']} locations evaluated)")
    return results


def stage_risk() -> dict[str, float]:
    print("[6/6b] Synthetic river-network risk demo ...", flush=True)
    try:
        graph = build_river_graph(SYNTHETIC_EDGES)
        risk_by_node = propagate_risk(graph, SOURCE_SITE, INITIAL_RISK, DECAY_PER_KM)
    except Exception as error:  # noqa: BLE001
        raise StageFailure(f"risk stage failed: {error}") from error
    target = qc_report_path("pipeline_risk_report.json")
    _write_json(target, {"origin": "synthetic", "risk_by_site": risk_by_node})
    print(f"      wrote {target} (source {SOURCE_SITE!r})")
    return risk_by_node


def main() -> None:
    print("OneAquaHealth end-to-end pipeline")
    print("=" * 40)
    try:
        observations = stage_snapshot()
        qc = stage_qc(observations)
        structural = stage_structural_validation(observations)
        official = stage_official_validation(observations)
        export = stage_fhir_export(observations)
        indices = stage_indices(observations)
        risk = stage_risk()
    except StageFailure as error:
        print(f"\nPIPELINE FAILED: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print("\n" + "=" * 40)
    print("Pipeline summary")
    print(f"  Observations processed : {len(observations)} (origin: real-sandbox)")
    print(f"  QC findings            : {qc['findings']}")
    print(f"  Structural findings    : {structural['resources_with_findings']}/{structural['resources_checked']}")
    print(f"  Official validation    : {official['status']}")
    print(f"  FHIR export            : {export['detected_issue_count']} DetectedIssue resources")
    print(f"  Indices evaluated      : {indices['evaluated_locations_count']} locations")
    reachable = sum(1 for value in risk.values() if value > 0.0)
    print(f"  Risk demo source       : {SOURCE_SITE} ({reachable} sites reachable; synthetic, illustrative topology)")


if __name__ == "__main__":
    main()
