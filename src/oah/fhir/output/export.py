"""Deterministic collection-Bundle export of sandbox Observation QC findings.

Determinism holds for a FIXED retrieval_date input: the same observations and the same
retrieval_date always produce byte-identical output. It does NOT make separate calls with a
fresh retrieval_date (e.g. the live POST /fhir/export endpoint, which stamps the current UTC instant
on every request) produce the same bundle_id across calls -- that id is derived from
retrieval_date via the Provenance/Bundle uuid5 chain, so it changes whenever the timestamp does.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from oah.fhir.output.builders import bundle, detected_issue, provenance, software_device
from oah.ingest.sources import Origin, SourceRecord, assert_single_origin, source_records
from oah.qc.policy import ALLOWED_UCUM_CODES, REVIEW_UCUM_CODES
from oah.qc.statistics import Finding, component_statistics

DEVICE_NAME = "oneaquahealth-qc"
DEVICE_VERSION = "0.1.0"
RULE_VERSION = "qc-1.0"


def _canonical_resource(resource: dict[str, Any]) -> str:
    return json.dumps(resource, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _finding_key(finding: Finding) -> tuple[str, str, str, str, str]:
    return (
        finding.resource_id,
        finding.code,
        finding.path,
        finding.severity,
        finding.message,
    )


def build_findings_bundle(
    observations: Iterable[dict[str, Any] | SourceRecord],
    retrieval_date: str,
    sandbox_url: str,
    allowed_ucum: set[str] | None = None,
    default_origin: Origin | None = None,
) -> dict[str, Any]:
    """Build a deterministic FHIR collection Bundle from sandbox Observations.

    Untagged dictionaries are accepted only when the caller declares ``default_origin``.
    """
    base_url = sandbox_url.rstrip("/")
    allowed = set(ALLOWED_UCUM_CODES if allowed_ucum is None else allowed_ucum)
    allowed.update(REVIEW_UCUM_CODES)
    records = source_records(observations, default_origin)
    origin = assert_single_origin(records)
    if origin == "synthetic":
        raise ValueError("Synthetic records must not be exported as real-derived findings.")
    ordered_observations = sorted((record.resource for record in records), key=_canonical_resource)
    device = software_device(DEVICE_NAME, DEVICE_VERSION)
    issues: list[dict[str, Any]] = []
    for observation in ordered_observations:
        observation_id = observation.get("id")
        if not isinstance(observation_id, str) or not observation_id:
            raise ValueError("Each sandbox Observation must have an id.")
        observation_ref = f"{base_url}/Observation/{observation_id}"
        findings = sorted(component_statistics(observation, allowed), key=_finding_key)
        issues.extend(
            detected_issue(finding, observation_ref, retrieval_date, RULE_VERSION)
            for finding in findings
        )
    target_refs = [f"urn:uuid:{issue['id']}" for issue in issues]
    generated_provenance = provenance(
        target_refs,
        f"urn:uuid:{device['id']}",
        base_url,
        retrieval_date,
        sorted({issue["code"]["text"] for issue in issues}),
    )
    return bundle([device, *issues, generated_provenance])


INDICATOR_DEVICE_NAME = "oneaquahealth-indicators"
INDICATOR_RULE_VERSION = "ccme-wqi-1.0"


def build_indicators_bundle(
    wqi_result: dict[str, Any],
    retrieval_date: str,
    sandbox_url: str,
) -> dict[str, Any]:
    """Build a collection Bundle of OAH-indicators Observations from a real-sandbox CCME WQI result.

    Deterministic for a fixed ``retrieval_date`` and input result. Locations without evaluable
    measurements are not exported (a missing Observation, never an invented value).
    """
    from oah.fhir.builders.observation import ccme_wqi_observation, derived_code_system

    if wqi_result.get("input_origin") != "real-sandbox":
        raise ValueError("Only real-sandbox indicator results may be exported as real-derived.")
    base_url = sandbox_url.rstrip("/")
    device = software_device(INDICATOR_DEVICE_NAME, DEVICE_VERSION)
    observations = [
        ccme_wqi_observation(entry, f"{base_url}/{entry['location_ref']}", retrieval_date, INDICATOR_RULE_VERSION)
        for entry in sorted(wqi_result["evaluated_locations"], key=lambda e: e["location_ref"])
    ]
    if not observations:
        # Provenance.target is 1..*: with nothing derived there is nothing to attest.
        return bundle([derived_code_system(), device])
    generated_provenance = provenance(
        [f"urn:uuid:{obs['id']}" for obs in observations],
        f"urn:uuid:{device['id']}",
        base_url,
        retrieval_date,
        [INDICATOR_RULE_VERSION],
    )
    return bundle([derived_code_system(), device, *observations, generated_provenance])
