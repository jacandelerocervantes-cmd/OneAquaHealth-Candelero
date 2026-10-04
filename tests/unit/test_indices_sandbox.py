"""Unit tests for apply_to_sandbox module and FHIR profile/code filtering."""

from oah.indices.apply_to_sandbox import apply_ccme_wqi_to_sandbox, list_sites_with_status
from oah.indices.water_parameter_limits import match_closed_parameter


def test_health_measure_profile_observations_are_excluded():
    mock_health_obs = [
        {
            "id": "obs-health-1",
            "meta": {"profile": ["http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-health-measure-oah"]},
            "subject": {"reference": "Location/Loc-Nordre-Aker"},
            "code": {
                "coding": [{"code": "diabetes-rate"}],
                "text": "% of people that do not have Diabetes, COPD or Cardiovascular disease",
            },
            "valueQuantity": {"value": 85.0, "unit": "%"},
        },
    ]

    results = apply_ccme_wqi_to_sandbox(mock_health_obs)
    assert results["skipped_health_measure_observations"] == 1
    assert results["evaluated_locations_count"] == 0
    assert results["skipped_locations_count"] == 0


def test_sulphate_observation_does_not_get_ph_limit():
    obs = {
        "code": {
            "coding": [{"code": "sulphate", "display": "Sulphate"}],
            "text": "Sulphate",
        }
    }
    matched = match_closed_parameter(obs)
    assert matched is not None
    param_name, limit, is_lower = matched
    assert param_name == "Sulphate"
    assert limit == 250.0
    assert is_lower is False


def test_apply_ccme_wqi_to_sandbox_with_mock_observations():
    mock_obs = [
        {
            "id": "obs-1",
            "meta": {"profile": ["http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"]},
            "subject": {"reference": "Location/Loc-Test-01"},
            "code": {"coding": [{"code": "nitrate"}]},
            "valueQuantity": {"value": 12.0, "unit": "mg/L", "system": "http://unitsofmeasure.org", "code": "mg/L"},
        },
        {
            "id": "obs-2",
            "meta": {"profile": ["http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"]},
            "subject": {"reference": "Location/Loc-Test-01"},
            "code": {"coding": [{"code": "ph"}]},
            "valueQuantity": {"value": 7.5, "unit": "pH"},
        },
        {
            "id": "obs-3",
            "meta": {"profile": ["http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"]},
            "subject": {"reference": "Location/Loc-Empty-02"},
            "code": {"coding": [{"code": "unknown-code"}]},
            "valueQuantity": {"value": 999.0, "unit": "unknown"},
        },
    ]

    results = apply_ccme_wqi_to_sandbox(mock_obs)
    assert results["input_origin"] == "real-sandbox"
    assert results["total_locations_found"] == 2
    assert results["evaluated_locations_count"] == 1
    assert results["skipped_locations_count"] == 1

    eval_loc = results["evaluated_locations"][0]
    assert eval_loc["location_ref"] == "Location/Loc-Test-01"
    assert 0.0 <= eval_loc["ccme_wqi"] <= 100.0
    assert eval_loc["confidence"] == "low_confidence"
    assert "below CCME 2001's recommended minimum" in eval_loc["confidence_note"]

    skip_loc = results["skipped_locations"][0]
    assert skip_loc["location_ref"] == "Location/Loc-Empty-02"
    assert "No evaluable physicochemical observations" in skip_loc["reason"]

    assert "NOT computed on real sandbox data" in results["macroinvertebrate_indices_note"]


# --- list_sites_with_status (GET /sites evidence) -----------------------------------------------


def _positioned_location(location_id: str, name: str, lat: float, lon: float) -> dict:
    return {
        "resourceType": "Location",
        "id": location_id,
        "name": name,
        "position": {"latitude": lat, "longitude": lon},
    }


def test_list_sites_with_status_joins_position_to_the_wqi_result():
    mock_obs = [
        {
            "id": "obs-1",
            "meta": {"profile": ["http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"]},
            "subject": {"reference": "Location/Loc-Test-01"},
            "code": {"coding": [{"code": "nitrate"}]},
            "valueQuantity": {"value": 12.0, "unit": "mg/L", "system": "http://unitsofmeasure.org", "code": "mg/L"},
        },
        {
            "id": "obs-2",
            "meta": {"profile": ["http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"]},
            "subject": {"reference": "Location/Loc-Empty-02"},
            "code": {"coding": [{"code": "unknown-code"}]},
            "valueQuantity": {"value": 999.0, "unit": "unknown"},
        },
    ]
    locations = [
        _positioned_location("Loc-Test-01", "Test reach", 35.334, 25.048),
        _positioned_location("Loc-Empty-02", "Empty reach", 40.1, 20.2),
    ]

    sites = list_sites_with_status(mock_obs, locations)
    by_id = {site["id"]: site for site in sites}

    assert by_id["Loc-Test-01"]["status"] == "evaluated"
    assert by_id["Loc-Test-01"]["latitude"] == 35.334
    assert by_id["Loc-Test-01"]["longitude"] == 25.048
    assert by_id["Loc-Test-01"]["ccme_class"] in ("Excellent", "Good", "Fair", "Marginal", "Poor")
    assert by_id["Loc-Test-01"]["ui_status"] in ("good", "moderate", "poor")

    assert by_id["Loc-Empty-02"]["status"] == "skipped"
    assert by_id["Loc-Empty-02"]["ccme_wqi"] is None
    assert by_id["Loc-Empty-02"]["ui_status"] == "unavailable"
    assert "No evaluable physicochemical observations" in by_id["Loc-Empty-02"]["reason"]


def test_list_sites_with_status_skips_locations_with_no_usable_position():
    locations = [
        {"resourceType": "Location", "id": "Loc-No-Position", "name": "No position"},
        _positioned_location("Loc-Has-Position", "Has position", 1.0, 2.0),
    ]
    sites = list_sites_with_status([], locations)
    assert [site["id"] for site in sites] == ["Loc-Has-Position"]


def test_list_sites_with_status_handles_a_location_with_no_observations_at_all():
    locations = [_positioned_location("Loc-No-Obs", "No observations", 1.0, 2.0)]
    sites = list_sites_with_status([], locations)
    assert len(sites) == 1
    assert sites[0]["status"] == "skipped"
    assert "No sandbox Observations reference this location" in sites[0]["reason"]
