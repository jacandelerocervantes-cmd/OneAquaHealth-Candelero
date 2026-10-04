"""Non-compensatory veto and eclipsing flag on the CCME WQI (synthetic inputs, no network)."""
import pytest

from oah.fhir.builders.observation import DERIVED_CODES, DERIVED_INDICATOR_SYSTEM, ccme_wqi_observation, veto_status_text
from oah.fhir.validate import validate_resource
from oah.indices.apply_to_sandbox import (
    ECLIPSABLE_CCME_CLASSES,
    VETO_EXCURSION,
    apply_ccme_wqi_to_sandbox,
    list_sites_with_status,
    veto_assessment,
)

PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-indicators-oah"


def _obs(oid, code, value, site="Location/S"):
    return {
        "resourceType": "Observation",
        "id": oid,
        "meta": {"profile": [PROFILE]},
        "subject": {"reference": site},
        "code": {"coding": [{"code": code}]},
        "valueQuantity": {"value": value, "system": "http://unitsofmeasure.org", "code": "ug/L" if code.endswith("-dissolved") else "mg/L"},
    }


COMPLIANT = [("ammonium", 0.1), ("nitrite", 0.1), ("sulphate", 100.0), ("total-phosphates", 0.05), ("zinc-dissolved", 10.0)]


def _site(nitrate):
    observations = [_obs(f"o{i}", code, value) for i, (code, value) in enumerate(COMPLIANT)]
    observations.append(_obs("nit", "nitrate", nitrate))
    return apply_ccme_wqi_to_sandbox(observations)["evaluated_locations"][0]


def test_a_severe_exceedance_among_compliant_parameters_is_eclipsed_by_the_composite_score():
    site = _site(300.0)  # 6x the 50 mg/L limit
    assert site["ccme_wqi"] > 65.0, "the composite alone would call this site acceptable (Fair)"
    assert site["veto_triggered"] and site["eclipsed"]
    assert site["veto_parameters"] == [
        {
            "parameter": "Nitrate",
            "worst_excursion": pytest.approx(5.0),
            "times_limit": pytest.approx(6.0),
            "worst_value": 300.0,
            "limit": 50.0,
            "unit": "mg/L",
        }
    ]
    assert site["worst_parameter_excursion"] == pytest.approx(5.0)


def test_marginal_exceedance_does_not_trigger_the_veto():
    site = _site(60.0)  # excursion 0.2 < VETO_EXCURSION
    assert site["failed_measurements"] == 1
    assert not site["veto_triggered"] and not site["eclipsed"] and site["veto_parameters"] == []


def test_veto_boundary_is_inclusive():
    assert veto_assessment([("P", 2.0, 1.0, False)], 90.0)["veto_triggered"]  # excursion exactly 1.0
    assert not veto_assessment([("P", 1.99, 1.0, False)], 90.0)["veto_triggered"]
    assert VETO_EXCURSION == 1.0


def test_veto_on_a_minimum_limit_parameter_uses_the_reciprocal_excursion():
    # dissolved oxygen 2 mg/L against a 6 mg/L minimum: excursion 6/2 - 1 = 2
    result = veto_assessment([("Dissolved Oxygen", 2.0, 6.0, True)], 95.0)
    assert result["veto_parameters"][0]["worst_excursion"] == pytest.approx(2.0) and result["eclipsed"]


def test_veto_without_eclipsing_when_the_composite_is_already_poor():
    assert ECLIPSABLE_CCME_CLASSES == {"Excellent", "Good", "Fair"}
    result = veto_assessment([("P", 10.0, 1.0, False)], 20.0)
    assert result["veto_triggered"] and not result["eclipsed"]


def test_worst_parameters_are_listed_worst_first_and_the_worst_test_per_parameter_counts():
    result = veto_assessment([("A", 3.0, 1.0, False), ("A", 9.0, 1.0, False), ("B", 5.0, 1.0, False), ("C", 1.0, 1.0, False)], 90.0)
    assert [(p["parameter"], p["worst_excursion"]) for p in result["veto_parameters"]] == [("A", 8.0), ("B", 4.0)]


def test_no_measurements_gives_a_clean_assessment():
    assert veto_assessment([], 100.0) == {"worst_parameter_excursion": 0.0, "veto_triggered": False, "veto_parameters": [], "eclipsed": False}


def test_sites_listing_exposes_the_veto_flags():
    locations = [{"id": "S", "name": "Site", "position": {"latitude": 1.0, "longitude": 2.0}}]
    observations = [_obs(f"o{i}", code, value) for i, (code, value) in enumerate(COMPLIANT)] + [_obs("nit", "nitrate", 300.0)]
    site = list_sites_with_status(observations, locations)[0]
    assert site["veto_triggered"] is True and site["eclipsed"] is True


def _evaluated(**extra):
    base = {
        "location_ref": "Location/S", "evaluable_measurements": 6, "distinct_parameters_count": 6,
        "failed_measurements": 1, "ccme_wqi": 70.4, "confidence": "normal", "confidence_note": "",
    }
    return {**base, **extra}


def test_exported_observation_carries_veto_components_and_stays_structurally_valid():
    site = _site(300.0)
    observation = ccme_wqi_observation({**site, "location_ref": "Location/S"}, "https://sandbox.example.test/fhir/Location/S", "2026-09-25T00:00:00+00:00", "ccme-wqi-1.0")
    components = {c["code"]["coding"][0]["code"]: c for c in observation["component"]}
    assert components["worst-parameter-excursion"]["valueQuantity"]["value"] == pytest.approx(5.0)
    assert components["veto-status"]["valueString"] == "eclipsed: Nitrate"
    assert all(c["code"]["coding"][0]["system"] == DERIVED_INDICATOR_SYSTEM for c in observation["component"])
    assert {"worst-parameter-excursion", "veto-status"} <= set(DERIVED_CODES)
    assert validate_resource(observation).findings == ()


def test_export_without_veto_fields_omits_those_components():
    observation = ccme_wqi_observation(_evaluated(), "https://sandbox.example.test/fhir/Location/S", "2026-09-25T00:00:00+00:00", "ccme-wqi-1.0")
    assert {c["code"]["coding"][0]["code"] for c in observation["component"]} == {"evaluable-measurements", "distinct-parameters", "failed-measurements"}


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ({"veto_triggered": False}, "none"),
        ({"veto_triggered": True, "eclipsed": False, "veto_parameters": [{"parameter": "A"}, {"parameter": "B"}]}, "veto: A, B"),
        ({"veto_triggered": True, "eclipsed": True, "veto_parameters": [{"parameter": "A"}]}, "eclipsed: A"),
    ],
)
def test_veto_status_text(extra, expected):
    assert veto_status_text(extra) == expected


def test_veto_entries_state_the_worst_value_the_limit_the_unit_and_the_factor():
    entry = veto_assessment([("Conductivity", 18400.0, 2500.0, False), ("Conductivity", 3000.0, 2500.0, False)], 95.0)["veto_parameters"][0]
    assert entry["worst_value"] == 18400.0 and entry["limit"] == 2500.0 and entry["unit"] == "uS/cm"
    assert entry["times_limit"] == pytest.approx(7.36) and entry["worst_excursion"] == pytest.approx(6.36)


def test_a_minimum_limit_veto_reports_the_factor_below_the_limit():
    entry = veto_assessment([("Dissolved Oxygen", 2.0, 6.0, True)], 95.0)["veto_parameters"][0]
    assert entry["worst_value"] == 2.0 and entry["times_limit"] == pytest.approx(3.0)  # limit is 3x the reading


def test_an_unknown_parameter_has_no_unit_but_is_still_reported():
    assert veto_assessment([("Mystery", 30.0, 10.0, False)], 95.0)["veto_parameters"][0]["unit"] is None
