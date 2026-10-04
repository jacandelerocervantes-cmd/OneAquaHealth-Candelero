"""Two-sided (range) objectives: a value fails below the lower bound or above the upper bound."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from oah.indices import apply_to_sandbox, water_parameter_limits
from oah.indices.apply_to_sandbox import apply_ccme_wqi_to_sandbox
from oah.indices.water_parameter_limits import (
    TWO_SIDED_LIMITS,
    classify_range_quantity,
    resolve_range_limit,
)
from oah.indices.water_quality import excursion

PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"


def test_registry_holds_only_the_signed_off_ph_range():
    assert TWO_SIDED_LIMITS == {"pH": (6.5, 9.5)}


def test_default_pipeline_fails_acidic_ph():
    result = apply_ccme_wqi_to_sandbox([_ph("a", 5.0)])
    assert result["evaluated_locations"][0]["ccme_wqi"] < 100.0


@pytest.mark.parametrize(
    ("value", "expected"),
    [(5.0, (6.5, True)), (6.49, (6.5, True)), (6.5, (9.5, False)), (7.0, (9.5, False)), (9.5, (9.5, False)), (10.0, (9.5, False))],
)
def test_resolve_range_limit_picks_violated_side(value, expected):
    assert resolve_range_limit(value, 6.5, 9.5) == expected


def test_resolve_range_limit_rejects_inverted_range():
    with pytest.raises(ValueError):
        resolve_range_limit(7.0, 9.5, 6.5)


def test_range_excursions_are_zero_inside_and_positive_outside():
    for value, positive in [(7.0, False), (6.5, False), (9.5, False), (5.0, True), (11.0, True)]:
        limit, is_lower = resolve_range_limit(value, 6.5, 9.5)
        assert (excursion(value, limit, is_lower) > 0) is positive


@given(st.floats(min_value=0.1, max_value=14.0), st.floats(min_value=0.1, max_value=6.9))
def test_range_excursion_matches_side(value, lower):
    upper = lower + 3.0
    limit, is_lower = resolve_range_limit(value, lower, upper)
    inside = lower <= value <= upper
    assert (excursion(value, limit, is_lower) == 0.0) is inside


def test_classify_range_quantity():
    assert classify_range_quantity({"value": 7.2}) == ("exact", 7.2)
    assert classify_range_quantity({"value": 7.2, "comparator": "<"}) == ("indeterminate", None)
    assert classify_range_quantity({"value": 7.2, "comparator": ">="}) == ("indeterminate", None)
    assert classify_range_quantity({"value": True}) == ("invalid", None)
    assert classify_range_quantity({}) == ("invalid", None)


def _ph(obs_id, value, comparator=None):
    quantity = {"value": value, "unit": "pH"}
    if comparator:
        quantity["comparator"] = comparator
    return {
        "id": obs_id,
        "meta": {"profile": [PROFILE]},
        "subject": {"reference": "Location/L1"},
        "code": {"coding": [{"code": "ph"}]},
        "valueQuantity": quantity,
    }


def _run(monkeypatch, observations, ranges):
    monkeypatch.setattr(water_parameter_limits, "TWO_SIDED_LIMITS", ranges)
    monkeypatch.setattr(apply_to_sandbox, "TWO_SIDED_LIMITS", ranges)
    return apply_ccme_wqi_to_sandbox(observations)


def test_acidic_ph_fails_with_range_but_passes_without(monkeypatch):
    acidic = [_ph("a", 5.0)]
    without = _run(monkeypatch, acidic, {})
    with_range = _run(monkeypatch, acidic, {"pH": (6.5, 9.5)})
    assert without["evaluated_locations"][0]["ccme_wqi"] == 100.0
    assert with_range["evaluated_locations"][0]["ccme_wqi"] < 100.0


def test_in_range_ph_passes(monkeypatch):
    result = _run(monkeypatch, [_ph("a", 7.5)], {"pH": (6.5, 9.5)})
    assert result["evaluated_locations"][0]["ccme_wqi"] == 100.0


def test_alkaline_ph_fails_with_range(monkeypatch):
    result = _run(monkeypatch, [_ph("a", 10.0)], {"pH": (6.5, 9.5)})
    assert result["evaluated_locations"][0]["ccme_wqi"] < 100.0


def test_censored_ph_is_indeterminate_with_range(monkeypatch):
    result = _run(monkeypatch, [_ph("a", 9.0, "<")], {"pH": (6.5, 9.5)})
    assert result["evaluated_locations_count"] == 0
    assert result["skipped_censored_quantities"] == 1
