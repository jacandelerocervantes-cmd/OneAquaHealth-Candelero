"""Regression tests for the 2026-09-29 independent audit of the index pipeline (findings F1-F9 and gaps)."""

import pytest

from oah.indices.apply_to_sandbox import DATA_QUALITY_KEYS, apply_ccme_wqi_to_sandbox, data_quality
from oah.indices.oxygen import collect_water_temperatures, effective_key, oxygen_saturation_mg_per_l
from oah.indices.regimes import country_for_location, regime_for_location
from oah.indices.water_parameter_limits import convert_to_unit

PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"
HEALTH_PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-health-measure-oah"
RIVER = [{"coding": [{"system": "http://snomed.info/sct", "code": "420531007"}]}]
IT_RIVER = {"id": "IT1", "type": RIVER, "description": "Stream (Campania, IT)"}
GR_RIVER = {"id": "GR1", "type": RIVER, "description": "Stream, Crete, Greece"}
PERIOD = {"start": "2020-01-01", "end": "2020-12-31"}


def _obs(loc, code, value, unit="mg/L", period=PERIOD, profile=PROFILE, quantity=None):
    obs = {
        "id": f"o-{loc}-{code}-{value}",
        "meta": {"profile": [profile]},
        "code": {"coding": [{"code": code}]},
        "valueQuantity": quantity if quantity is not None else {"value": value, "unit": unit, "code": unit},
    }
    if loc is not None:
        obs["subject"] = {"reference": f"Location/{loc}"}
    if period is not None:
        obs["effectivePeriod"] = period
    return obs


def _run(observations, locations=None):
    result = apply_ccme_wqi_to_sandbox(observations, locations)
    return result, (result["evaluated_locations"][0] if result["evaluated_locations"] else None)


# F1 ---------------------------------------------------------------------------------------------
def test_negative_oxygen_is_excluded_for_italian_rivers_like_elsewhere():
    temp = _obs("IT1", "water temperature", 20.0, "Cel")
    result, entry = _run([temp, _obs("IT1", "dissolved-oxygen", -5.0)], [IT_RIVER])
    assert entry is None
    assert result["skipped_physically_impossible_observations"] == 1


# F2 ---------------------------------------------------------------------------------------------
def test_unusable_and_subjectless_observations_are_counted_not_lost():
    observations = [
        _obs("L1", "nitrate", None, quantity={"unit": "mg/L", "code": "mg/L"}),
        _obs("L1", "nitrate", None, quantity={"value": "abc", "code": "mg/L"}),
        _obs("L1", "sulphate", 100.0),
        _obs(None, "sulphate", 100.0),
    ]
    result, entry = _run(observations)
    assert result["skipped_invalid_quantity_observations"] == 2
    assert result["skipped_no_subject_observations"] == 1
    assert entry["scorable_observations"] == 3
    assert entry["evaluable_measurements"] + result["skipped_invalid_quantity_observations"] == entry["scorable_observations"]
    assert entry["excluded_data_quality_observations"] == 2


# F3 / F6 ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("order", [(5.0, 25.0), (25.0, 5.0)])
def test_conflicting_temperatures_never_depend_on_input_order(order):
    observations = [_obs("IT1", "water temperature", t, "Cel") for t in order] + [_obs("IT1", "dissolved-oxygen", 9.0)]
    result, entry = _run(observations, [IT_RIVER])
    assert entry is None
    assert result["skipped_ambiguous_temperature_for_saturation_observations"] == 1


def test_identical_duplicate_temperatures_still_pair():
    observations = [_obs("IT1", "water temperature", 20.0, "Cel"), _obs("IT1", "water temperature", 20.0, "Cel")]
    observations.append(_obs("IT1", "dissolved-oxygen", 9.0))
    _, entry = _run(observations, [IT_RIVER])
    assert entry["ccme_wqi"] == 100.0


@pytest.mark.parametrize("value", [41.0, -0.5])
def test_out_of_range_temperature_is_reported_as_unusable_not_missing(value):
    observations = [_obs("IT1", "water temperature", value, "Cel"), _obs("IT1", "dissolved-oxygen", 9.0)]
    result, entry = _run(observations, [IT_RIVER])
    assert entry is None
    assert result["skipped_unusable_temperature_for_saturation_observations"] == 1
    assert result["skipped_no_temperature_for_saturation_observations"] == 0


def test_period_keys_are_normalised_but_a_period_and_an_instant_do_not_pair():
    utc_z = {"effectiveDateTime": "2020-01-01T00:00:00Z"}
    utc_offset = {"effectiveDateTime": "2020-01-01T00:00:00+00:00"}
    assert effective_key(utc_z) == effective_key(utc_offset)
    assert effective_key({"effectivePeriod": PERIOD}) != effective_key(utc_z)
    assert effective_key({}) is None


# F4 ---------------------------------------------------------------------------------------------
def test_temperature_from_a_rejected_profile_is_not_used_for_pairing():
    health_temperature = _obs("IT1", "water temperature", 20.0, "Cel", profile=HEALTH_PROFILE)
    assert collect_water_temperatures([health_temperature]) == {}
    result, entry = _run([health_temperature, _obs("IT1", "dissolved-oxygen", 9.0)], [IT_RIVER])
    assert entry is None
    assert result["skipped_no_temperature_for_saturation_observations"] == 1


# F5 ---------------------------------------------------------------------------------------------
def test_data_quality_block_carries_every_documented_counter():
    result, _ = _run([_obs("L1", "sulphate", 100.0)])
    block = data_quality(result)
    assert set(block) == set(DATA_QUALITY_KEYS)
    for key in ("skipped_non_finite_observations", "skipped_invalid_quantity_observations", "skipped_no_subject_observations"):
        assert key in block


# F7 ---------------------------------------------------------------------------------------------
def test_ucum_bracket_ph_and_lowercase_litre_units_are_accepted():
    assert convert_to_unit(7.0, "[pH]", "pH") == 7.0
    assert convert_to_unit(500.0, "ug/l", "mg/L") == pytest.approx(0.5)
    assert convert_to_unit(1.0, "mg/l", "ug/L") == pytest.approx(1000.0)
    _, entry = _run([_obs("L1", "ph", 7.0, "[pH]")])
    assert entry["ccme_wqi"] == 100.0


# F8 ---------------------------------------------------------------------------------------------
def test_explicit_json_nulls_do_not_raise():
    assert country_for_location({"id": "z", "partOf": None, "description": None}) is None
    assert regime_for_location({"id": "z", "type": None}) == "drinking"
    assert regime_for_location({"id": "z", "type": [None]}) == "drinking"


@pytest.mark.parametrize(
    ("description", "country"),
    [("Crete, Greece.", "GR"), ("Town (Rome, Italy)", "IT"), ("Oslo, Norway", "NO"), ("Madrid, Spain", None)],
)
def test_country_names_with_punctuation(description, country):
    assert country_for_location({"id": "x", "description": description}) == country


def test_ancestor_depth_and_cycles_are_bounded():
    chain = {f"L{i}": {"id": f"L{i}", "description": "", "partOf": {"reference": f"Location/L{i + 1}"}} for i in range(6)}
    chain["L6"] = {"id": "L6", "description": "Root, Greece"}
    assert country_for_location(chain["L1"], chain) == "GR"  # five ancestors above L1
    assert country_for_location(chain["L0"], chain) is None  # six ancestors: out of reach
    loop = {"A": {"id": "A", "partOf": {"reference": "Location/B"}}, "B": {"id": "B", "partOf": {"reference": "Location/A"}}}
    assert country_for_location(loop["A"], loop) is None


def test_long_comma_heavy_description_is_handled_quickly():
    assert country_for_location({"id": "x", "description": "(" + "a," * 5000 + "IT"}) is None


# Gaps ------------------------------------------------------------------------------------------
def test_ph_mix_through_the_pipeline_matches_the_hand_calculation():
    observations = [_obs("L1", "ph", v, "[pH]", period={"start": f"20{i}0-01-01", "end": f"20{i}0-12-31"}) for i, v in enumerate([5.0, 7.0, 10.0, 7.5], start=1)]
    _, entry = _run(observations)
    # F1 = 100 (the one parameter fails), F2 = 50 (2 of 4 tests), F3 from excursions 6.5/5-1=0.3 and 10/9.5-1=0.0526
    assert entry["ccme_wqi"] == pytest.approx(35.279, abs=0.01)
    assert entry["failed_measurements"] == 2


@pytest.mark.parametrize(("ph", "fails"), [(6.5, False), (9.5, False), (6.49, True), (9.51, True)])
def test_ph_exactly_at_the_range_bounds_through_the_pipeline(ph, fails):
    _, entry = _run([_obs("L1", "ph", ph, "[pH]")])
    assert (entry["failed_measurements"] == 1) is fails


@pytest.mark.parametrize(("end", "score_is_full"), [("2036-01-11", True), ("2036-01-12", False)])
def test_lead_limit_changes_at_the_boundary_through_the_pipeline(end, score_is_full):
    observation = _obs("L1", "lead-dissolved", 7.0, "ug/L", period={"start": "2035-06-01", "end": end})
    _, entry = _run([observation])
    assert (entry["ccme_wqi"] == 100.0) is score_is_full


def test_dated_lead_limit_is_ignored_in_the_surface_regime():
    river = {"id": "R1", "type": RIVER, "description": ""}
    observation = _obs("R1", "lead-dissolved", 1.1, "ug/L", period={"start": "2040-01-01", "end": "2040-12-31"})
    _, entry = _run([observation], [river])
    assert entry["ccme_wqi"] == 100.0  # 1.1 <= 1.2 surface EQS; the 2036 drinking limit (5) is not applied here


@pytest.mark.parametrize(("share", "passes"), [(0.79, False), (0.81, True), (1.19, True), (1.21, False)])
def test_italian_oxygen_deviation_boundary(share, passes):
    sat = oxygen_saturation_mg_per_l(20.0)
    observations = [_obs("IT1", "water temperature", 20.0, "Cel"), _obs("IT1", "dissolved-oxygen", share * sat)]
    _, entry = _run(observations, [IT_RIVER])
    assert (entry["ccme_wqi"] == 100.0) is passes


def test_censored_oxygen_is_indeterminate_with_a_temperature():
    observations = [
        _obs("IT1", "water temperature", 20.0, "Cel"),
        _obs("IT1", "dissolved-oxygen", None, quantity={"value": 5.0, "comparator": "<", "unit": "mg/L", "code": "mg/L"}),
        _obs("IT1", "sulphate", 100.0),
    ]
    result, _ = _run(observations, [IT_RIVER])
    assert result["skipped_censored_quantities"] == 1


def test_oxygen_in_ug_per_l_is_converted_before_the_saturation():
    sat = oxygen_saturation_mg_per_l(20.0)
    observations = [_obs("IT1", "water temperature", 20.0, "Cel"), _obs("IT1", "dissolved-oxygen", sat * 1000.0, "ug/L")]
    _, entry = _run(observations, [IT_RIVER])
    assert entry["ccme_wqi"] == 100.0


def test_temperature_edges_zero_and_forty_degrees_are_usable():
    for edge in (0.0, 40.0):
        found = collect_water_temperatures([_obs("IT1", "water temperature", edge, "Cel")])
        assert list(found.values()) == [edge]


def test_greek_ammonium_and_nitrite_through_the_pipeline():
    def entry_for(code, value):
        return _run([_obs("GR1", code, value)], [GR_RIVER])[1]["ccme_wqi"]

    assert entry_for("ammonium", 0.07) == 100.0 and entry_for("ammonium", 0.09) < 100.0  # 0.0773 mg/L NH4
    assert entry_for("nitrite", 0.025) == 100.0 and entry_for("nitrite", 0.03) < 100.0  # 0.02628 mg/L NO2


def test_italian_ammonium_with_a_microgram_unit():
    assert _run([_obs("IT1", "ammonium", 50.0, "ug/L")], [IT_RIVER])[1]["ccme_wqi"] == 100.0
    assert _run([_obs("IT1", "ammonium", 80.0, "ug/L")], [IT_RIVER])[1]["ccme_wqi"] < 100.0
