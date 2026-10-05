"""The measurements export never writes digits that are only an artefact of a division (docs/fhir_mapping.md)."""
from __future__ import annotations

from oah.fhir.output.measurements import measurements_bundle

RETRIEVED = "2026-10-05T00:00:00Z"


def _observation(value: float | int, **extra: float) -> dict:
    payload = {
        "location_id": "X1", "origin": "real-eea-waterbase", "attribution": "EEA Waterbase (CC BY 4.0)", "site": {"name": "Lake X"},
        "records": [{"parameter": "Total phosphorus", "value": value, "unit": "mg/L", "year": 2020, "statistic": "mean", "status": "not-scored",
                     "origin": "real-eea-waterbase", **extra}],
    }
    body = measurements_bundle(payload, RETRIEVED)
    return next(e["resource"] for e in body["entry"] if e["resource"]["resourceType"] == "Observation")


def test_a_long_float_is_written_with_six_significant_digits():
    observation = _observation(15.945454545454544, min=10.123456789, max=20.987654321)
    assert observation["valueQuantity"]["value"] == 15.9455
    note = observation["note"][0]["text"]
    assert "15.945454" not in note and "observed range 10.1235 to 20.9877" in note
    assert "15.9455 mg/L" in observation["text"]["div"]


def test_integers_and_short_floats_are_untouched():
    assert _observation(31)["valueQuantity"]["value"] == 31
    assert _observation(0.015)["valueQuantity"]["value"] == 0.015
