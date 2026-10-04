"""Contracts for OAH-indicators Observation export (synthetic test inputs, no network)."""
import json

import pytest

from oah.fhir.builders.observation import DERIVED_CODES, DERIVED_INDICATOR_SYSTEM, INDICATORS_PROFILE
from oah.fhir.output.export import build_indicators_bundle
from oah.fhir.validate import validate_resource

DATE = "2026-09-23T10:00:00+00:00"
BASE = "https://sandbox.example.test/fhir"


def _result(origin="real-sandbox"):
    return {
        "input_origin": origin,
        "evaluated_locations": [
            {
                "location_ref": "Location/Loc-B",
                "total_observations": 4,
                "evaluable_measurements": 6,
                "distinct_parameters_count": 3,
                "failed_measurements": 1,
                "ccme_wqi": 72.5,
                "confidence": "low_confidence",
                "confidence_note": "low confidence (below CCME 2001's recommended minimum of 4 variables)",
            },
            {
                "location_ref": "Location/Loc-A",
                "total_observations": 9,
                "evaluable_measurements": 12,
                "distinct_parameters_count": 5,
                "failed_measurements": 0,
                "ccme_wqi": 100.0,
                "confidence": "normal",
                "confidence_note": "",
            },
        ],
        "skipped_locations": [],
    }


def _by_type(bundle):
    out = {}
    for entry in bundle["entry"]:
        out.setdefault(entry["resource"]["resourceType"], []).append(entry["resource"])
    return out


def test_bundle_contains_one_observation_per_evaluated_location_sorted():
    resources = _by_type(build_indicators_bundle(_result(), DATE, BASE))
    subjects = [o["subject"]["reference"] for o in resources["Observation"]]
    assert subjects == [f"{BASE}/Location/Loc-A", f"{BASE}/Location/Loc-B"]
    assert len(resources["Provenance"]) == len(resources["Device"]) == len(resources["CodeSystem"]) == 1


def test_observation_satisfies_indicators_profile_constraints():
    obs = _by_type(build_indicators_bundle(_result(), DATE, BASE))["Observation"][0]
    assert obs["meta"]["profile"] == [INDICATORS_PROFILE]
    assert obs["status"] == "final"
    assert obs["subject"]["reference"] and obs["effectiveDateTime"] == DATE
    assert obs["performer"], "profile requires performer 1.."
    assert set(obs["valueQuantity"]) >= {"value", "system", "code"}
    assert obs["interpretation"][0]["text"] == "Excellent"
    for coding in [obs["code"]["coding"][0], *(c["code"]["coding"][0] for c in obs["component"])]:
        assert coding["system"] == DERIVED_INDICATOR_SYSTEM
        assert coding["code"] in DERIVED_CODES


def test_every_generated_resource_is_r4b_structurally_valid():
    bundle = build_indicators_bundle(_result(), DATE, BASE)
    assert validate_resource(bundle).findings == ()
    for entry in bundle["entry"]:
        resource = entry["resource"]
        if resource["resourceType"] in {"Observation"}:
            assert validate_resource(resource).findings == ()


def test_origin_tag_and_provenance_targets_every_observation():
    resources = _by_type(build_indicators_bundle(_result(), DATE, BASE))
    obs_refs = {f"urn:uuid:{o['id']}" for o in resources["Observation"]}
    assert {t["reference"] for t in resources["Provenance"][0]["target"]} == obs_refs
    assert all(o["meta"]["tag"][0]["code"] == "real-derived" for o in resources["Observation"])


def test_deterministic_for_fixed_date_and_sensitive_to_it():
    a = json.dumps(build_indicators_bundle(_result(), DATE, BASE), sort_keys=True)
    b = json.dumps(build_indicators_bundle(_result(), DATE, BASE), sort_keys=True)
    c = json.dumps(build_indicators_bundle(_result(), "2026-09-24T10:00:00+00:00", BASE), sort_keys=True)
    assert a == b and a != c


def test_synthetic_or_unlabelled_results_are_refused():
    for origin in ("synthetic", None):
        with pytest.raises(ValueError, match="real-sandbox"):
            build_indicators_bundle(_result(origin), DATE, BASE)


def test_no_evaluated_locations_yields_bundle_without_observations():
    empty = _result()
    empty["evaluated_locations"] = []
    resources = _by_type(build_indicators_bundle(empty, DATE, BASE))
    assert "Observation" not in resources and "Provenance" not in resources
    assert validate_resource(build_indicators_bundle(empty, DATE, BASE)).findings == ()
