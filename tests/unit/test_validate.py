from oah.fhir.output import builders
from oah.fhir.validate import OAH_LOCATION_PROFILE, OAH_OBSERVATION_PROFILE, validate_resource
from oah.qc.statistics import Finding

def codes(result):
    return {finding.code for finding in result.findings}

def location():
    return {"resourceType": "Location", "meta": {"profile": [OAH_LOCATION_PROFILE]}, "identifier": [{"value": "x"}], "name": "Site", "mode": "instance"}

def observation():
    return {"resourceType": "Observation", "meta": {"profile": [OAH_OBSERVATION_PROFILE]}, "status": "final", "code": {"text": "x"}, "component": [{"code": {"text": "x"}, "valueString": "x"}]}

def test_location_profile():
    result = validate_resource(location())
    assert result.findings == ()
    assert result.applied_profiles == (OAH_LOCATION_PROFILE,)

def test_location_missing_identifier():
    resource = location()
    resource.pop("identifier")
    assert codes(validate_resource(resource)) == {"location-identifier"}

def test_location_missing_name():
    resource = location()
    resource.pop("name")
    assert codes(validate_resource(resource)) == {"location-name"}

def test_location_wrong_mode():
    resource = location()
    resource["mode"] = "kind"
    assert codes(validate_resource(resource)) == {"location-mode"}

def test_location_invalid_position_is_structural():
    resource = location()
    resource["position"] = {"longitude": 1}
    assert "r4b-structure" in codes(validate_resource(resource))

def test_location_multiple_profile_defects_are_not_hidden():
    resource = location()
    resource.pop("name")
    resource["mode"] = "kind"
    assert codes(validate_resource(resource)) == {"location-name", "location-mode"}

def test_observation_profile():
    assert validate_resource(observation()).findings == ()
    resource = observation()
    resource["valueQuantity"] = {"value": 1}
    resource.pop("component")
    assert codes(validate_resource(resource)) == {"observation-value", "observation-component"}

def test_observation_any_value_choice_is_prohibited():
    for key in ("valueBoolean", "valueRange"):
        resource = observation()
        resource[key] = True if key == "valueBoolean" else {"low": {"value": 1}}
        assert "observation-value" in codes(validate_resource(resource))

def test_unsupported_and_invalid_and_no_profile():
    assert codes(validate_resource({"resourceType": "Patient"})) == {"unsupported-resource-type"}
    assert codes(validate_resource({"resourceType": "Group"})) == {"r4b-structure"}  # supported, but missing required fields
    assert codes(validate_resource({"resourceType": "Observation", "code": {"text": "x"}})) == {"r4b-structure"}
    resource = observation()
    resource.pop("meta")
    assert validate_resource(resource).applied_profiles == ()


def test_generated_standard_resources_are_structurally_valid_without_profiles():
    device = builders.software_device("oah-pipeline", "0.1.0")
    finding = Finding("statistical-order", "error", "obs-1", "component", "Invalid order.")
    issue = builders.detected_issue(
        finding,
        "https://sandbox.example.test/fhir/Observation/obs-1",
        "2026-09-21T18:22:15+00:00",
        "qc-1.0",
    )
    generated_provenance = builders.provenance(
        [f"urn:uuid:{issue['id']}"],
        f"urn:uuid:{device['id']}",
        "https://sandbox.example.test/fhir",
        "2026-09-21T18:22:15+00:00",
        ["statistical-order"],
    )
    generated_bundle = builders.bundle([device, issue, generated_provenance])
    for resource in (device, issue, generated_provenance, generated_bundle):
        result = validate_resource(resource)
        assert result.findings == ()
        assert result.applied_profiles == ()
