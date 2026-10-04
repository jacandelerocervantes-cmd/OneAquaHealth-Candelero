"""FSH-derived checks for ObservationIndicatorsOah and ObservationHealthMeasureOah, and the wider structural models.

Rules come from ig/oah/input/fsh/profiles/observation-indicators-oah.fsh and observation-health-measure-oah.fsh.
The official HL7 validator remains the conformance evidence; these checks are a fast offline subset.
"""
import copy
import json

import pytest

from oah.fhir.validate import (
    OAH_HEALTH_MEASURE_PROFILE,
    OAH_INDICATORS_PROFILE,
    _reference_type,
    validate_resource,
)
from oah.paths import fixtures_real_path


def _indicators():
    return {
        "resourceType": "Observation",
        "id": "ind-1",
        "meta": {"profile": [OAH_INDICATORS_PROFILE]},
        "status": "final",
        "code": {"coding": [{"system": "https://example.test/cs", "code": "x"}]},
        "subject": {"reference": "Location/Loc-1"},
        "effectiveDateTime": "2026-09-26T00:00:00Z",
        "performer": [{"reference": "Organization/o1"}],
        "valueQuantity": {"value": 3.0, "system": "http://unitsofmeasure.org", "code": "1"},
        "component": [
            {"code": {"text": "c1"}, "valueString": "text"},
            {"code": {"text": "c2"}, "valueQuantity": {"value": 1}},
            {"code": {"text": "c3"}, "valueCodeableConcept": {"text": "t"}},
        ],
    }


def _health():
    return {
        "resourceType": "Observation",
        "id": "hm-1",
        "meta": {"profile": [OAH_HEALTH_MEASURE_PROFILE]},
        "status": "final",
        "code": {"coding": [{"system": "https://example.test/cs", "code": "x"}]},
        "subject": {"reference": "Location/Loc-1"},
        "effectiveDateTime": "2026-09-26T00:00:00Z",
        "valueQuantity": {"value": 12.5, "system": "http://unitsofmeasure.org", "code": "%"},
        "focus": [{"reference": "Group/g1"}],
    }


def _codes(resource):
    return {finding.code for finding in validate_resource(resource).findings}


def test_valid_resources_pass_and_report_the_applied_profile():
    indicators, health = validate_resource(_indicators()), validate_resource(_health())
    assert indicators.findings == () and indicators.applied_profiles == (OAH_INDICATORS_PROFILE,)
    assert health.findings == () and health.applied_profiles == (OAH_HEALTH_MEASURE_PROFILE,)


def _without(key):
    def mutate(resource):
        del resource[key]
    return mutate


def _set(key, value):
    def mutate(resource):
        resource[key] = value
    return mutate


INDICATOR_BREAKS = [
    ("status", _set("status", "preliminary"), "indicators-status"),
    ("code", _without("code"), "indicators-code"),
    ("subject", _without("subject"), "indicators-subject"),
    ("subject-type", _set("subject", {"reference": "Patient/p1"}), "indicators-subject-type"),
    ("effective", _without("effectiveDateTime"), "indicators-effective"),
    ("performer", _without("performer"), "indicators-performer"),
    ("value-type", lambda r: (r.pop("valueQuantity"), r.update(valueString="high")), "indicators-value-type"),
    ("specimen-type", _set("specimen", {"reference": "Device/d1"}), "indicators-specimen-type"),
    ("component-value", lambda r: r["component"][0].pop("valueString"), "indicators-component-value"),
    ("component-value-type", lambda r: (r["component"][0].pop("valueString"), r["component"][0].update(valueBoolean=True)), "indicators-component-value-type"),
]


@pytest.mark.parametrize(("name", "mutate", "code"), INDICATOR_BREAKS, ids=[b[0] for b in INDICATOR_BREAKS])
def test_each_indicators_rule_fires(name, mutate, code):
    resource = _indicators()
    mutate(resource)
    assert code in _codes(resource), name


HEALTH_BREAKS = [
    ("status", _set("status", "amended"), "health-measure-status"),
    ("code", _without("code"), "health-measure-code"),
    ("subject", _without("subject"), "health-measure-subject"),
    ("subject-type", _set("subject", {"reference": "Group/g1"}), "health-measure-subject-type"),
    ("effective", _without("effectiveDateTime"), "health-measure-effective"),
    ("value-type", lambda r: (r.pop("valueQuantity"), r.update(valueInteger=3)), "health-measure-value-type"),
    ("focus-type", _set("focus", [{"reference": "Location/l1"}]), "health-measure-focus-type"),
]


@pytest.mark.parametrize(("name", "mutate", "code"), HEALTH_BREAKS, ids=[b[0] for b in HEALTH_BREAKS])
def test_each_health_measure_rule_fires(name, mutate, code):
    resource = _health()
    mutate(resource)
    assert code in _codes(resource), name


def test_health_measure_does_not_require_performer_and_indicators_do_not_require_focus():
    health = _health()
    assert "performer" not in health and _codes(health) == set()
    assert "focus" not in _indicators() and _codes(_indicators()) == set()


def test_rules_apply_only_to_resources_that_declare_the_profile():
    resource = _indicators()
    resource["meta"]["profile"] = []
    del resource["status"]  # still structurally required, so only the structural finding remains
    assert not any(code.startswith("indicators-") for code in _codes(resource))


def test_a_resource_with_both_profiles_reports_both_rule_sets():
    resource = _indicators()
    resource["meta"]["profile"] = [OAH_INDICATORS_PROFILE, OAH_HEALTH_MEASURE_PROFILE]
    resource["status"] = "preliminary"
    assert {"indicators-status", "health-measure-status"} <= _codes(resource)


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ({"reference": "Location/l1"}, "Location"),
        ({"reference": "https://sandbox.example.test/fhir/Location/l1"}, "Location"),
        ({"reference": "https://sandbox.example.test/fhir/Location/l1/_history/2"}, "Location"),
        ({"reference": "urn:uuid:1234"}, None),
        ({"reference": "#contained"}, None),
        ({"reference": "l1"}, None),
        ({"reference": "Location/l1", "type": "Patient"}, "Patient"),
        ({"display": "no reference"}, None),
        ("not a dict", None),
    ],
)
def test_reference_type(reference, expected):
    assert _reference_type(reference) == expected


def test_unresolvable_references_are_not_flagged():
    resource = _indicators()
    resource["subject"] = {"reference": "urn:uuid:11111111-1111-1111-1111-111111111111"}
    assert "indicators-subject-type" not in _codes(resource)


def test_effective_period_and_the_other_effective_forms_are_accepted():
    for key, value in (("effectivePeriod", {"start": "2026-01-01"}), ("effectiveInstant", "2026-01-01T00:00:00Z")):
        resource = _indicators()
        del resource["effectiveDateTime"]
        resource[key] = value
        assert "indicators-effective" not in _codes(resource)


def test_real_fixtures_of_every_supported_type_have_no_findings():
    types = set()
    for file in fixtures_real_path().glob("*.json"):
        if file.name.endswith(".metadata.json"):
            continue
        resource = json.loads(file.read_text(encoding="utf-8"))
        types.add(resource["resourceType"])
        assert validate_resource(resource).findings == (), file.name
    assert {"Group", "Library", "Location", "Observation"} <= types, "Group and Library used to be unsupported"


@pytest.mark.parametrize(
    "resource",
    [
        {"resourceType": "Organization", "id": "o1", "name": "Agency"},
        {"resourceType": "Specimen", "id": "s1", "status": "available"},
        {"resourceType": "Group", "id": "g1", "type": "person", "actual": False},
        {"resourceType": "Library", "id": "l1", "status": "active", "type": {"text": "logic-library"}},
    ],
)
def test_newly_supported_structural_models_accept_valid_and_reject_invalid_resources(resource):
    assert validate_resource(resource).findings == ()
    broken = copy.deepcopy(resource)
    broken["status" if "status" in broken else "id"] = ["not", "a", "scalar"]
    assert "r4b-structure" in _codes(broken)


def test_unknown_resource_types_are_still_reported_as_unsupported():
    assert _codes({"resourceType": "Patient"}) == {"unsupported-resource-type"}
    assert _codes({}) == {"unsupported-resource-type"}
