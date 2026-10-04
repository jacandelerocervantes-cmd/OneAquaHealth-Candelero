"""Contracts for generated finding exports using synthetic test data."""

import pytest

from oah.fhir.output.export import build_findings_bundle
from oah.qc.report import build_report

DATE = "2026-09-21T18:22:15+00:00"
BASE = "https://sandbox.example.test/fhir"


def _component(code, value):
    return {
        "code": {"coding": [{"code": code}]},
        "valueQuantity": {
            "value": value,
            "system": "http://unitsofmeasure.org",
            "code": "ug/L",
        },
    }


def _observations():
    # Synthetic test data: deliberately invalid statistical component order.
    return [
        {
            "resourceType": "Observation",
            "id": "observation-b",
            "component": [_component("minimum", 4), _component("maximum", 1)],
        },
        {
            "resourceType": "Observation",
            "id": "observation-a",
            "component": [_component("minimum", 3), _component("maximum", 2)],
        },
    ]


def _resources(findings_bundle):
    return [entry["resource"] for entry in findings_bundle["entry"]]


def test_export_has_one_device_one_provenance_and_one_issue_per_finding():
    findings_bundle = build_findings_bundle(_observations(), DATE, BASE, default_origin="real-sandbox")
    resources = _resources(findings_bundle)
    issues = [resource for resource in resources if resource["resourceType"] == "DetectedIssue"]
    assert len([resource for resource in resources if resource["resourceType"] == "Device"]) == 1
    assert len([resource for resource in resources if resource["resourceType"] == "Provenance"]) == 1
    assert len(issues) == 2
    assert {issue["implicated"][0]["reference"] for issue in issues} == {
        f"{BASE}/Observation/observation-a",
        f"{BASE}/Observation/observation-b",
    }


def test_export_is_deterministic_for_a_fixed_retrieval_date():
    first = build_findings_bundle(_observations(), DATE, BASE, default_origin="real-sandbox")
    second = build_findings_bundle(list(reversed(_observations())), DATE, BASE, default_origin="real-sandbox")
    assert first == second


def test_observation_without_an_id_is_rejected():
    # Synthetic test data: a sandbox-shaped Observation cannot be exported without an id.
    with pytest.raises(ValueError, match="must have an id"):
        build_findings_bundle([{"resourceType": "Observation", "component": []}], DATE, BASE, default_origin="real-sandbox")


def test_observation_without_findings_yields_no_detected_issue():
    # Synthetic test data: ordered statistics and an allowed unit produce no finding.
    observations = [
        {
            "resourceType": "Observation",
            "id": "clean",
            "component": [_component("minimum", 1), _component("maximum", 2)],
        }
    ]
    resources = _resources(build_findings_bundle(observations, DATE, BASE, default_origin="real-sandbox"))
    assert not [resource for resource in resources if resource["resourceType"] == "DetectedIssue"]


def test_bundle_has_no_text_and_all_entries_have_full_url():
    findings_bundle = build_findings_bundle(_observations(), DATE, BASE, default_origin="real-sandbox")
    assert "text" not in findings_bundle
    assert all(entry.get("fullUrl") for entry in findings_bundle["entry"])


def test_report_and_export_agree_that_ph_is_not_a_ucum_error():
    # Synthetic test data: pH requires review but is not a ucum-unit error.
    observations = [
        {
            "resourceType": "Observation",
            "id": "ph-observation",
            "component": [_component("minimum", 6), _component("maximum", 8)],
        }
    ]
    for component in observations[0]["component"]:
        component["valueQuantity"]["code"] = "pH"
    report = build_report(observations, default_origin="real-sandbox")
    exported = _resources(build_findings_bundle(observations, DATE, BASE, default_origin="real-sandbox"))
    exported_ucum = [
        resource
        for resource in exported
        if resource["resourceType"] == "DetectedIssue" and resource["code"]["text"] == "ucum-unit"
    ]
    assert report["findings"].get("ucum-unit", 0) == len(exported_ucum) == 0


def test_provenance_targets_every_detected_issue():
    findings_bundle = build_findings_bundle(_observations(), DATE, BASE, default_origin="real-sandbox")
    resources = _resources(findings_bundle)
    issues = [resource for resource in resources if resource["resourceType"] == "DetectedIssue"]
    generated_provenance = next(
        resource for resource in resources if resource["resourceType"] == "Provenance"
    )
    assert {target["reference"] for target in generated_provenance["target"]} == {
        f"urn:uuid:{issue['id']}" for issue in issues
    }


def test_tagging_is_idempotent_and_never_relabels_a_synthetic_resource():
    import pytest

    from oah.fhir.output.builders import ORIGIN_SYSTEM, _tag

    resource = {"resourceType": "Device"}
    _tag(_tag(resource))
    assert resource["meta"]["tag"] == [{"system": ORIGIN_SYSTEM, "code": "real-derived"}]
    with pytest.raises(ValueError, match="synthetic"):
        _tag({"resourceType": "Device", "meta": {"tag": [{"code": "synthetic"}]}})
