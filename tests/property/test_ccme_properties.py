"""Property tests of the CCME WQI, its excursions, the veto and unit conversion (synthetic inputs)."""
import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from oah.indices.apply_to_sandbox import veto_assessment
from oah.indices.water_parameter_limits import convert_to_unit, exact_numeric_value
from oah.indices.water_quality import ccme_wqi, classify_ccme_wqi, excursion

positive = st.floats(min_value=0.001, max_value=1e6, allow_nan=False, allow_infinity=False)
measurement = st.tuples(st.sampled_from(["A", "B", "C", "D"]), positive, positive, st.booleans())
measurements = st.lists(measurement, min_size=1, max_size=25)
mass_units = st.sampled_from(["ng/L", "ug/L", "mg/L", "g/L"])


@given(measurements)
@settings(max_examples=300, deadline=None)
def test_the_index_is_always_within_zero_and_one_hundred_and_classifiable(items):
    score = ccme_wqi(items)
    assert 0.0 <= score <= 100.0
    assert classify_ccme_wqi(score) in {"Excellent", "Good", "Fair", "Marginal", "Poor"}


@given(measurements, st.randoms(use_true_random=False))
@settings(max_examples=200, deadline=None)
def test_the_index_does_not_depend_on_the_order_of_the_measurements(items, rnd):
    shuffled = items[:]
    rnd.shuffle(shuffled)
    assert ccme_wqi(shuffled) == pytest.approx(ccme_wqi(items), rel=1e-9, abs=1e-9)


@given(positive, positive, st.booleans())
def test_an_excursion_is_never_negative_and_is_zero_exactly_when_the_objective_is_met(observed, limit, is_lower):
    value = excursion(observed, limit, is_lower)
    met = observed >= limit if is_lower else observed <= limit
    assert value >= 0.0 and (value == 0.0) == met


@given(measurements, st.integers(0, 24), st.floats(min_value=1.0, max_value=50.0))
@settings(max_examples=300, deadline=None)
def test_making_one_measurement_worse_can_never_improve_the_index(items, index, factor):
    index %= len(items)
    name, observed, limit, is_lower = items[index]
    worse = (name, observed / factor if is_lower else observed * factor, limit, is_lower)
    assert ccme_wqi(items[:index] + [worse] + items[index + 1:]) <= ccme_wqi(items) + 1e-9


@given(measurements)
@settings(max_examples=200, deadline=None)
def test_a_perfect_dataset_scores_one_hundred(items):
    perfect = [(name, limit * 2 if is_lower else limit / 2, limit, is_lower) for name, _o, limit, is_lower in items]
    assert ccme_wqi(perfect) == 100.0


@given(measurements)
@settings(max_examples=200, deadline=None)
def test_the_veto_is_consistent_with_the_worst_excursion(items):
    result = veto_assessment(items, 100.0)
    worst = max(excursion(observed, limit, low) for _name, observed, limit, low in items)
    assert result["worst_parameter_excursion"] == pytest.approx(worst)
    assert result["veto_triggered"] == (worst >= 1.0)
    assert result["eclipsed"] == result["veto_triggered"]  # a composite of 100 is always in an eclipsable class
    ordered = [entry["worst_excursion"] for entry in result["veto_parameters"]]
    assert ordered == sorted(ordered, reverse=True)


@given(positive, mass_units, mass_units)
def test_unit_conversion_round_trips(value, source, target):
    there = convert_to_unit(value, source, target)
    assert there is not None
    assert convert_to_unit(there, target, source) == pytest.approx(value, rel=1e-9)


@given(positive)
def test_conductivity_conversion_is_a_factor_of_one_thousand(value):
    assert convert_to_unit(value, "mS/cm", "uS/cm") == pytest.approx(value * 1000)


@given(st.one_of(st.text(max_size=5), st.none(), st.booleans(), st.floats(allow_nan=False, allow_infinity=False)))
def test_only_plain_numbers_are_exact_values(value):
    result = exact_numeric_value({"value": value})
    if isinstance(value, float):
        assert result == value
    else:
        assert result is None


@given(st.floats(allow_nan=False, allow_infinity=False), st.sampled_from(["<", "<=", ">", ">="]))
def test_a_comparator_makes_a_value_inexact(value, comparator):
    assert exact_numeric_value({"value": value, "comparator": comparator}) is None
    assert not math.isnan(value)
