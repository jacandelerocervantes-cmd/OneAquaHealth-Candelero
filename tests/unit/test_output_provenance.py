"""Audit batch B: every index output states its limits' provenance and that it is not a compliance finding."""

import pytest

from oah.api.app import app
from oah.fhir.builders.observation import ccme_wqi_observation
from oah.indices.apply_to_sandbox import apply_ccme_wqi_to_sandbox
from oah.indices.regimes import DRINKING, INTERPRETATION_NOTICE, SURFACE, limit_basis

PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"
RIVER = [{"coding": [{"system": "http://snomed.info/sct", "code": "420531007"}]}]


@pytest.mark.parametrize(
    ("parameter", "regime", "country", "expected_start"),
    [
        ("Nitrate", DRINKING, None, "legal: Directive (EU) 2020/2184 Annex I Part B"),
        ("Ammonium", DRINKING, None, "legal indicator: Directive (EU) 2020/2184 Annex I Part C"),
        ("Lead dissolved", DRINKING, None, "legal: Directive (EU) 2020/2184 Annex I Part B (10 ug/L until 2036"),
        ("Zinc dissolved", DRINKING, None, "convention:"),
        ("Water temperature", DRINKING, None, "convention:"),
        ("Mercury dissolved", SURFACE, None, "legal: Directive 2013/39/EU"),
        ("Cadmium dissolved", SURFACE, None, "not scored"),
        ("Arsenic dissolved", SURFACE, None, "proxy, drinking-water value on a river site"),
        ("Nitrate", SURFACE, "IT", "national: DM 260/2010 LIMeco (Italy)"),
        ("Dissolved Oxygen", SURFACE, "GR", "national: HWQI"),
        ("Dissolved oxygen saturation deviation", SURFACE, "IT", "national: DM 260/2010"),
        ("Nitrate", SURFACE, "NO", "proxy, drinking-water value on a river site"),
    ],
)
def test_limit_basis(parameter, regime, country, expected_start):
    assert limit_basis(parameter, regime, country).startswith(expected_start)


def _observation(code, value, unit):
    return {
        "id": f"o-{code}",
        "meta": {"profile": [PROFILE]},
        "subject": {"reference": "Location/R1"},
        "code": {"coding": [{"code": code}]},
        "valueQuantity": {"value": value, "unit": unit, "code": unit},
    }


def test_each_evaluated_site_lists_the_basis_of_every_parameter_it_used():
    river = {"id": "R1", "type": RIVER, "description": "Stream (Campania, IT)"}
    result = apply_ccme_wqi_to_sandbox([_observation("nitrate", 1.0, "mg/L"), _observation("zinc-dissolved", 10.0, "ug/L")], [river])
    entry = result["evaluated_locations"][0]
    assert set(entry["limit_basis"]) == {"Nitrate", "Zinc dissolved"}
    assert entry["limit_basis"]["Nitrate"].startswith("national: DM 260/2010")
    assert entry["limit_basis"]["Zinc dissolved"].startswith("convention")  # no legal source anywhere for zinc
    assert "not legal limits" in result["objective_limits_source"]


def test_openapi_documents_the_interpretation_notice_on_index_outputs():
    schemas = app.openapi()["components"]["schemas"]
    for name in ("IndexResponse", "SitesResponse", "IndicatorsExportResponse"):
        assert "interpretation_notice" in schemas[name]["properties"]


def test_exported_indicator_observation_carries_the_notice():
    evaluated = {
        "location_ref": "Location/S", "ccme_wqi": 90.0, "confidence": "normal", "confidence_note": "",
        "evaluable_measurements": 3, "distinct_parameters_count": 3, "failed_measurements": 0,
        "worst_parameter_excursion": 0.0, "veto_triggered": False, "veto_parameters": [], "eclipsed": False,
    }
    observation = ccme_wqi_observation(evaluated, "https://sandbox.example.test/fhir/Location/S", "2026-09-25T00:00:00+00:00", "ccme-wqi-1.0")
    assert {"text": INTERPRETATION_NOTICE} in observation["note"]
    assert "not a legal compliance determination" in INTERPRETATION_NOTICE
