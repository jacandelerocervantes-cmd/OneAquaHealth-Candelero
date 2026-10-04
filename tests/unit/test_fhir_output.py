"""Contracts for the deterministic FHIR output builders (synthetic test inputs only)."""

import pytest
from fhir.resources.R4B.bundle import Bundle
from fhir.resources.R4B.detectedissue import DetectedIssue
from fhir.resources.R4B.device import Device
from fhir.resources.R4B.provenance import Provenance

from oah.fhir.output import builders
from oah.qc.statistics import Finding

BASE = "https://sandbox.example.test/fhir"
DATE = "2026-09-21T18:22:15+00:00"


def finding(severity="error", code="statistical-order", path="component"):
    return Finding(code, severity, "obs-1", path, "minimum <= median is required.")


def issue(severity="error", code="statistical-order", rule_version="qc-1.0", observation="obs-1"):
    return builders.detected_issue(
        finding(severity, code), f"{BASE}/Observation/{observation}", DATE, rule_version
    )


def make_provenance(issue_resource, device):
    return builders.provenance(
        [f"urn:uuid:{issue_resource['id']}"],
        f"urn:uuid:{device['id']}",
        BASE,
        DATE,
        ["statistical-order"],
    )


def origin_codes(resource):
    return [tag["code"] for tag in resource["meta"]["tag"]]


# --- Device ------------------------------------------------------------------------------


def test_device_is_valid_and_tagged():
    device = builders.software_device("oah-pipeline", "0.1.0")
    Device.model_validate(device)
    assert device["deviceName"][0]["name"] == "oah-pipeline"
    assert device["version"][0]["value"] == "0.1.0"
    assert origin_codes(device) == ["real-derived"]
    assert device["text"]["status"] == "generated"


def test_device_id_is_deterministic_and_version_sensitive():
    first = builders.software_device("oah-pipeline", "0.1.0")
    again = builders.software_device("oah-pipeline", "0.1.0")
    other = builders.software_device("oah-pipeline", "0.2.0")
    assert first["id"] == again["id"]
    assert first["id"] != other["id"]


# --- DetectedIssue -----------------------------------------------------------------------


def test_detected_issue_is_valid_and_references_the_observation():
    resource = issue()
    DetectedIssue.model_validate(resource)
    assert resource["status"] == "final"
    assert resource["code"]["text"] == "statistical-order"
    assert resource["implicated"] == [{"reference": f"{BASE}/Observation/obs-1"}]
    assert resource["identifiedDateTime"] == DATE
    assert origin_codes(resource) == ["real-derived"]


def test_error_findings_map_to_high_severity():
    assert issue(severity="error")["severity"] == "high"


def test_other_findings_map_to_moderate_severity():
    assert issue(severity="warning")["severity"] == "moderate"


def test_detected_issue_id_is_deterministic():
    assert issue()["id"] == issue()["id"]


def test_detected_issue_id_changes_with_rule_version():
    assert issue(rule_version="qc-1.0")["id"] != issue(rule_version="qc-2.0")["id"]


def test_detected_issue_id_changes_with_observation():
    assert issue(observation="obs-1")["id"] != issue(observation="obs-2")["id"]


def test_detected_issue_id_changes_with_finding_code():
    assert issue(code="statistical-order")["id"] != issue(code="mean-range")["id"]


# --- Provenance --------------------------------------------------------------------------


def test_provenance_is_valid_and_source_is_a_reference():
    device = builders.software_device("oah-pipeline", "0.1.0")
    resource = make_provenance(issue(), device)
    Provenance.model_validate(resource)
    what = resource["entity"][0]["what"]
    assert "uri" not in what
    assert what["reference"] == BASE
    assert resource["entity"][0]["role"] == "source"
    assert resource["recorded"] == DATE


def test_provenance_points_at_the_generated_resources():
    device = builders.software_device("oah-pipeline", "0.1.0")
    detected = issue()
    resource = make_provenance(detected, device)
    assert resource["target"] == [{"reference": f"urn:uuid:{detected['id']}"}]
    assert resource["agent"][0]["who"] == {"reference": f"urn:uuid:{device['id']}"}


def test_provenance_id_is_deterministic():
    device = builders.software_device("oah-pipeline", "0.1.0")
    detected = issue()
    assert make_provenance(detected, device)["id"] == make_provenance(detected, device)["id"]


# --- Bundle ------------------------------------------------------------------------------


def make_bundle():
    device = builders.software_device("oah-pipeline", "0.1.0")
    detected = issue()
    return builders.bundle([device, detected, make_provenance(detected, device)])


def test_bundle_entries_have_unique_full_urls_matching_ids():
    bundle = make_bundle()
    urls = [entry["fullUrl"] for entry in bundle["entry"]]
    assert len(set(urls)) == len(urls)
    for entry in bundle["entry"]:
        assert entry["fullUrl"] == f"urn:uuid:{entry['resource']['id']}"


def test_bundle_is_a_tagged_collection_with_an_id():
    bundle = make_bundle()
    assert bundle["type"] == "collection"
    assert bundle["id"]
    assert origin_codes(bundle) == ["real-derived"]


def test_bundle_id_is_deterministic():
    assert make_bundle()["id"] == make_bundle()["id"]


def test_bundle_refuses_resources_without_an_id():
    with pytest.raises(ValueError):
        builders.bundle([{"resourceType": "Device"}])


def test_bundle_has_no_narrative_and_is_structurally_valid():
    bundle = make_bundle()
    assert "text" not in bundle
    Bundle.model_validate(bundle)


# --- meta handling -----------------------------------------------------------------------


def test_tagging_preserves_existing_meta():
    resource = {"resourceType": "Device", "meta": {"profile": ["http://example.test/p"], "tag": [{"code": "keep"}]}}
    tagged = builders._tag(resource)
    assert tagged["meta"]["profile"] == ["http://example.test/p"]
    assert [tag["code"] for tag in tagged["meta"]["tag"]] == ["keep", "real-derived"]
