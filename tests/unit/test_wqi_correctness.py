"""Regression tests for three CCME WQI defects found on 2026-09-25 (synthetic inputs, no network).

1. Dissolved oxygen (a minimum-limit parameter) was scored in the wrong direction.
2. The standard deviation component was scored as a level of the parameter.
3. Observations whose own summary statistics were inconsistent were scored anyway.
"""
import pytest

from oah.indices.apply_to_sandbox import apply_ccme_wqi_to_sandbox
from oah.indices.water_parameter_limits import representative_quantity
from oah.indices.water_quality import ccme_wqi, excursion

PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"


def _q(value):
    return {"value": value, "system": "http://unitsofmeasure.org", "code": "mg/L"}


def _component(code, value):
    return {"code": {"coding": [{"code": code}]}, "valueQuantity": _q(value)}


def _obs(oid, param_code, components, site="Location/S1"):
    return {
        "resourceType": "Observation",
        "id": oid,
        "meta": {"profile": [PROFILE]},
        "subject": {"reference": site},
        "code": {"coding": [{"code": param_code}]},
        "component": components,
    }


def _stats(minimum, median, maximum, average, std):
    return [
        _component("minimum", minimum),
        _component("median", median),
        _component("maximum", maximum),
        _component("average", average),
        _component("std-dev", std),
    ]


@pytest.mark.parametrize(
    ("observed", "limit", "is_lower", "expected"),
    [
        (10.0, 5.0, False, 1.0),
        (5.0, 5.0, False, 0.0),
        (3.0, 5.0, False, 0.0),
        (3.0, 6.0, True, 1.0),
        (6.0, 6.0, True, 0.0),
        (9.0, 6.0, True, 0.0),
        (0.0, 6.0, True, 999.0),
        (10.0, 0.0, False, 999.0),
    ],
)
def test_excursion(observed, limit, is_lower, expected):
    assert excursion(observed, limit, is_lower) == expected


def test_low_dissolved_oxygen_fails_and_high_passes_with_explicit_direction():
    assert ccme_wqi([("Dissolved Oxygen", 3.0, 6.0, True)]) < 100.0
    assert ccme_wqi([("Dissolved Oxygen", 9.0, 6.0, True)]) == 100.0


def test_name_guess_handles_the_display_name_with_a_space():
    # the fallback used for plain triples previously missed "Dissolved Oxygen" (space, not underscore)
    assert ccme_wqi([("Dissolved Oxygen", 3.0, 6.0)]) == ccme_wqi([("Dissolved Oxygen", 3.0, 6.0, True)]) < 100.0


def test_apply_scores_low_dissolved_oxygen_as_a_failure():
    result = apply_ccme_wqi_to_sandbox([_obs("do", "dissolved-oxygen", _stats(2.0, 3.0, 4.0, 3.0, 0.5))])
    site = result["evaluated_locations"][0]
    assert site["failed_measurements"] == 1 and site["ccme_wqi"] < 100.0


def test_apply_scores_healthy_dissolved_oxygen_as_a_pass():
    result = apply_ccme_wqi_to_sandbox([_obs("do", "dissolved-oxygen", _stats(7.0, 8.0, 9.0, 8.0, 0.5))])
    assert result["evaluated_locations"][0]["ccme_wqi"] == 100.0


def test_one_summary_observation_is_one_test_and_std_dev_is_never_scored():
    # std-dev 900 would be a huge "exceedance" of a 50 mg/L nitrate limit if it were scored
    result = apply_ccme_wqi_to_sandbox([_obs("n", "nitrate", _stats(1.0, 2.0, 3.0, 2.0, 900.0))])
    site = result["evaluated_locations"][0]
    assert site["evaluable_measurements"] == 1 and site["failed_measurements"] == 0
    assert site["ccme_wqi"] == 100.0


def test_median_is_the_representative_statistic_and_average_the_fallback():
    quantity, reason = representative_quantity(_obs("x", "nitrate", _stats(1.0, 2.0, 3.0, 2.5, 0.1)))
    assert quantity["value"] == 2.0 and reason is None
    no_median = [c for c in _stats(1.0, 2.0, 3.0, 2.5, 0.1) if c["code"]["coding"][0]["code"] != "median"]
    assert representative_quantity(_obs("x", "nitrate", no_median))[0]["value"] == 2.5


def test_observations_with_inconsistent_statistics_are_not_scored_and_are_counted():
    # real-sandbox pattern: average/min/max in different units than the median
    bad = _obs("bad", "nitrate", _stats(62000.0, 6.9, 76000.0, 69000.0, 0.9))
    result = apply_ccme_wqi_to_sandbox([bad])
    assert result["skipped_qc_inconsistent_observations"] == 1
    assert result["evaluated_locations_count"] == 0
    assert representative_quantity(bad) == (None, "qc-inconsistent")


def test_observations_without_a_usable_statistic_or_quantity_are_skipped():
    only_extremes = _obs("e", "nitrate", [_component("minimum", 1.0), _component("maximum", 3.0)])
    assert representative_quantity(only_extremes) == (None, "no-representative-statistic")
    assert representative_quantity({"resourceType": "Observation"}) == (None, "no-quantity")
    result = apply_ccme_wqi_to_sandbox([only_extremes])
    assert result["skipped_no_representative_observations"] == 1


def test_plain_value_quantity_observation_is_still_scored():
    obs = {
        "resourceType": "Observation",
        "id": "p",
        "meta": {"profile": [PROFILE]},
        "subject": {"reference": "Location/S1"},
        "code": {"coding": [{"code": "nitrate"}]},
        "valueQuantity": _q(80.0),
    }
    site = apply_ccme_wqi_to_sandbox([obs])["evaluated_locations"][0]
    assert site["failed_measurements"] == 1


# --- units: limits are compared only after conversion to the limit's own unit ---------------------

from oah.indices.water_parameter_limits import CLOSED_PARAM_MAPPING, PARAMETER_UNITS, convert_to_unit  # noqa: E402


def _plain(oid, code, value, unit, comparator=None):
    quantity = {"value": value, "system": "http://unitsofmeasure.org"}
    if unit is not None:
        quantity["code"] = unit
    if comparator:
        quantity["comparator"] = comparator
    return {
        "resourceType": "Observation", "id": oid, "meta": {"profile": [PROFILE]},
        "subject": {"reference": "Location/U"}, "code": {"coding": [{"code": code}]}, "valueQuantity": quantity,
    }


def test_every_scored_parameter_declares_the_unit_of_its_limit():
    assert {v[0] for v in CLOSED_PARAM_MAPPING.values()} <= set(PARAMETER_UNITS)


@pytest.mark.parametrize(
    ("value", "source", "target", "expected"),
    [
        (2.0, "mg/L", "ug/L", 2000.0), (1500.0, "ug/L", "mg/L", 1.5), (1.2, "mS/cm", "uS/cm", 1200.0),
        (5.0, "mg/L", "mg/L", 5.0), (0.001, "g/L", "mg/L", 1.0), (7.4, None, "pH", 7.4),
        (3.0, "mg/L", "uS/cm", None), (3.0, "Cel", "mg/L", None), (3.0, "furlong", "mg/L", None), (3.0, None, "mg/L", None),
    ],
)
def test_convert_to_unit(value, source, target, expected):
    result = convert_to_unit(value, source, target)
    assert result == (pytest.approx(expected) if expected is not None else None)


def test_conductivity_reported_in_millisiemens_is_compared_after_conversion():
    passing = apply_ccme_wqi_to_sandbox([_plain("c1", "conductivity", 1.2, "mS/cm")])["evaluated_locations"][0]
    failing = apply_ccme_wqi_to_sandbox([_plain("c2", "conductivity", 3.0, "mS/cm")])["evaluated_locations"][0]
    assert passing["failed_measurements"] == 0 and passing["ccme_wqi"] == 100.0
    assert failing["failed_measurements"] == 1 and failing["worst_parameter_excursion"] == pytest.approx(0.2)


def test_a_concentration_reported_in_another_mass_unit_is_converted_before_the_comparison():
    high = apply_ccme_wqi_to_sandbox([_plain("n1", "nitrate", 60000.0, "ug/L")])["evaluated_locations"][0]
    low = apply_ccme_wqi_to_sandbox([_plain("n2", "nitrate", 10000.0, "ug/L")])["evaluated_locations"][0]
    assert high["failed_measurements"] == 1 and low["failed_measurements"] == 0


def test_censored_bounds_are_converted_too():
    result = apply_ccme_wqi_to_sandbox([_plain("n3", "nitrate", 20000.0, "ug/L", comparator="<")])
    assert result["censored_quantities_counted_as_pass"] == 1  # "< 20 mg/L" is below the 50 mg/L limit


@pytest.mark.parametrize("unit", ["furlong", "Cel", "uS/cm", None])
def test_unknown_incompatible_or_missing_units_are_skipped_and_counted_not_guessed(unit):
    result = apply_ccme_wqi_to_sandbox([_plain("n4", "nitrate", 99.0, unit)])
    assert result["skipped_unit_mismatch_observations"] == 1
    assert result["evaluated_locations_count"] == 0


def test_ph_without_a_unit_code_is_accepted_but_temperature_needs_celsius():
    assert apply_ccme_wqi_to_sandbox([_plain("p", "ph", 7.4, None)])["evaluated_locations_count"] == 1
    assert apply_ccme_wqi_to_sandbox([_plain("t", "watertemperature", 20.0, "degF")])["skipped_unit_mismatch_observations"] == 1


def test_unit_exclusions_lower_the_confidence_of_a_site():
    observations = [_plain("a", "nitrate", 5.0, "mg/L"), _plain("b", "nitrate", 5.0, "furlong"), _plain("c", "nitrate", 5.0, "furlong")]
    site = apply_ccme_wqi_to_sandbox(observations)["evaluated_locations"][0]
    assert site["excluded_data_quality_observations"] == 2 and site["confidence"] == "low_confidence"
