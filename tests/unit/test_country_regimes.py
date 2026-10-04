"""Country-dependent surface limits (Italy, DM 260/2010 LIMeco), oxygen as % saturation, phosphate basis."""

import pytest

from oah.indices.apply_to_sandbox import apply_ccme_wqi_to_sandbox
from oah.indices.oxygen import (
    oxygen_saturation_mg_per_l,
    saturation_deviation_percent,
    saturation_test,
)
from oah.indices.regimes import (
    COUNTRY_SURFACE_LIMITS,
    NO2_PER_N,
    NH4_PER_N,
    NO3_PER_N,
    PO4_PER_P,
    countries_by_location_ref,
    country_for_location,
)

PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"
RIVER_TYPE = [{"coding": [{"system": "http://snomed.info/sct", "code": "420531007"}]}]


def _loc(loc_id, description="", country_hint=None, part_of=None):
    loc = {"id": loc_id, "type": RIVER_TYPE, "description": description}
    if part_of:
        loc["partOf"] = {"reference": f"Location/{part_of}"}
    return loc


IT_RIVER = _loc("IT1", "Stream near Benevento (Campania, IT)")
GR_RIVER = _loc("Loc-Almyros", "Coastal stream segment")
NO_RIVER = _loc("NO1", "Stream in Oslo (Nordre Aker, NO)")
PERIOD = {"start": "2020-01-01", "end": "2020-12-31"}


def _obs(loc, code, value, unit, period=PERIOD):
    return {
        "id": f"o-{loc}-{code}",
        "meta": {"profile": [PROFILE]},
        "subject": {"reference": f"Location/{loc}"},
        "code": {"coding": [{"code": code}]},
        "effectivePeriod": period,
        "valueQuantity": {"value": value, "unit": unit, "code": unit},
    }


def _run(observations, locations):
    result = apply_ccme_wqi_to_sandbox(observations, locations)
    return result, (result["evaluated_locations"][0] if result["evaluated_locations"] else None)


@pytest.mark.parametrize(("temp", "expected"), [(0.0, 14.62), (20.0, 9.09), (25.0, 8.26)])
def test_oxygen_saturation_matches_standard_methods_table(temp, expected):
    assert oxygen_saturation_mg_per_l(temp) == pytest.approx(expected, abs=0.02)


def test_oxygen_saturation_decreases_with_temperature_and_rejects_out_of_range():
    values = [oxygen_saturation_mg_per_l(t) for t in range(0, 41, 5)]
    assert values == sorted(values, reverse=True)
    for bad in (-1.0, 41.0, float("nan")):
        with pytest.raises(ValueError):
            oxygen_saturation_mg_per_l(bad)


def test_saturation_deviation_zero_at_saturation_and_symmetric_shape():
    sat = oxygen_saturation_mg_per_l(15.0)
    assert saturation_deviation_percent(sat, 15.0) == pytest.approx(0.0, abs=1e-9)
    assert saturation_deviation_percent(sat * 0.5, 15.0) == pytest.approx(50.0)
    assert saturation_deviation_percent(sat * 1.5, 15.0) == pytest.approx(50.0)


def test_saturation_test_outcomes():
    assert saturation_test({"value": 8.0}, None) == ("no-temperature", None)
    assert saturation_test({"value": 8.0, "comparator": "<"}, 15.0) == ("indeterminate", None)
    assert saturation_test({"value": True}, 15.0) == ("invalid", None)
    kind, deviation = saturation_test({"value": 8.0}, 15.0)
    assert kind == "exact" and deviation is not None and deviation >= 0.0


def test_phosphate_limit_is_phosphorus_converted_to_po4():
    assert PO4_PER_P == pytest.approx(3.066, abs=0.001)
    assert COUNTRY_SURFACE_LIMITS["IT"]["Total phosphates"] == pytest.approx(0.3066, abs=0.001)


def test_country_from_description_override_and_parent():
    assert country_for_location(IT_RIVER) == "IT"
    assert country_for_location(NO_RIVER) == "NO"
    assert country_for_location(GR_RIVER) == "GR"
    assert country_for_location(_loc("X", "no country here")) is None
    child = _loc("C", "site", part_of="IT1")
    assert country_for_location(child, {"IT1": IT_RIVER}) == "IT"
    assert countries_by_location_ref([IT_RIVER, GR_RIVER, _loc("X", "")]) == {"Location/IT1": "IT", "Location/Loc-Almyros": "GR"}


def test_phosphate_between_eu_proxy_and_italian_limit():
    # 0.2 mg/L PO4: over the 0.10 proxy, under the Italian 0.3066 mg/L (100 ug/l P) LIMeco boundary.
    _, italy = _run([_obs("IT1", "total-phosphates", 0.2, "mg/L")], [IT_RIVER])
    _, norway = _run([_obs("NO1", "total-phosphates", 0.2, "mg/L")], [NO_RIVER])
    assert italy["ccme_wqi"] == 100.0 and italy["limit_country"] == "IT"
    assert norway["ccme_wqi"] < 100.0 and norway["limit_country"] == "NO"
    _, above = _run([_obs("IT1", "total-phosphates", 0.4, "mg/L")], [IT_RIVER])
    assert above["ccme_wqi"] < 100.0


def test_italian_oxygen_is_scored_as_saturation_deviation():
    temp = _obs("IT1", "water temperature", 20.0, "Cel")
    saturated = _obs("IT1", "dissolved-oxygen", 9.0, "mg/L")  # about 99 % at 20 C
    depleted = _obs("IT1", "dissolved-oxygen", 5.0, "mg/L")  # about 55 %: deviation 45 > 20
    _, good = _run([temp, saturated], [IT_RIVER])
    _, bad = _run([temp, depleted], [IT_RIVER])
    assert good["ccme_wqi"] == 100.0 and bad["ccme_wqi"] < 100.0


def test_italian_oxygen_without_temperature_is_skipped_and_counted():
    result, entry = _run([_obs("IT1", "dissolved-oxygen", 9.0, "mg/L")], [IT_RIVER])
    assert entry is None
    assert result["skipped_no_temperature_for_saturation_observations"] == 1


def test_temperature_is_not_scored_for_italian_rivers_but_is_elsewhere():
    hot = _obs("IT1", "water temperature", 32.0, "Cel")
    result, entry = _run([hot], [IT_RIVER])
    assert entry is None and result["skipped_interpretive_only_observations"] == 1
    _, norway = _run([_obs("NO1", "water temperature", 32.0, "Cel")], [NO_RIVER])
    assert norway["ccme_wqi"] < 100.0  # 32 C exceeds the 25 C proxy


def test_other_countries_keep_the_mg_per_l_oxygen_minimum():
    _, norway = _run([_obs("NO1", "dissolved-oxygen", 6.2, "mg/L")], [NO_RIVER])
    assert norway["ccme_wqi"] == 100.0  # 6.2 >= 6.0 mg/L minimum


def test_nitrogen_limits_are_converted_from_n_to_the_ion():
    assert NO3_PER_N == pytest.approx(4.427, abs=0.001)
    assert NH4_PER_N == pytest.approx(1.288, abs=0.001)
    limits = COUNTRY_SURFACE_LIMITS["IT"]
    assert limits["Nitrate"] == pytest.approx(5.312, abs=0.005)  # 1.2 mg/l as N
    assert limits["Ammonium"] == pytest.approx(0.0773, abs=0.0005)  # 0.06 mg/l as N


def test_italian_river_nitrate_and_ammonium_use_the_limeco_boundary():
    # 20 mg/L nitrate is far under the 50 mg/L drinking limit but over the Italian river boundary.
    _, italy = _run([_obs("IT1", "nitrate", 20.0, "mg/L")], [IT_RIVER])
    _, norway = _run([_obs("NO1", "nitrate", 20.0, "mg/L")], [NO_RIVER])
    assert italy["ccme_wqi"] < 100.0 and norway["ccme_wqi"] == 100.0
    _, ok = _run([_obs("IT1", "nitrate", 4.0, "mg/L")], [IT_RIVER])
    assert ok["ccme_wqi"] == 100.0
    _, ammonium = _run([_obs("IT1", "ammonium", 0.2, "mg/L")], [IT_RIVER])
    assert ammonium["ccme_wqi"] < 100.0  # 0.2 mg/L NH4 exceeds 0.0773


def test_country_from_real_sandbox_descriptions():
    parent = {"id": "Giofyros", "description": "Giofyros River, Crete, Greece"}
    child = {"id": "Loc-Giofyros", "description": "Urban stream segment sampled for OAH monitoring", "partOf": {"reference": "Location/Giofyros"}}
    assert country_for_location(parent) == "GR"
    assert country_for_location(child, {"Giofyros": parent}) == "GR"
    assert country_for_location({"id": "590", "description": "Urban stream monitoring site C5, Coimbra"}) is None
    assert country_for_location({"id": "454", "description": ""}) is None


def test_greek_hwqi_limits_are_converted_from_the_published_boundaries():
    limits = COUNTRY_SURFACE_LIMITS["GR"]
    assert NO2_PER_N == pytest.approx(3.2845, abs=0.001)
    assert limits["Nitrate"] == pytest.approx(2.656, abs=0.005)  # 0.60 mg/L as N
    assert limits["Ammonium"] == pytest.approx(0.0773, abs=0.0005)  # 0.06 mg/L as N
    assert limits["Nitrite"] == pytest.approx(0.02628, abs=0.0001)  # 8 ug/L as N, in mg/L NO2
    assert limits["Total phosphates"] == pytest.approx(0.5059, abs=0.001)  # 165 ug/L as P, in mg/L PO4
    assert limits["Dissolved Oxygen"] == 6.4


def test_greek_river_uses_hwqi_boundaries_and_ignores_temperature():
    def score(code, value, unit="mg/L"):
        return _run([_obs("Loc-Almyros", code, value, unit)], [GR_RIVER])[1]

    assert score("nitrate", 2.0)["ccme_wqi"] == 100.0 and score("nitrate", 3.0)["ccme_wqi"] < 100.0
    assert score("dissolved-oxygen", 6.5)["ccme_wqi"] == 100.0 and score("dissolved-oxygen", 6.2)["ccme_wqi"] < 100.0
    assert score("total-phosphates", 0.4)["ccme_wqi"] == 100.0 and score("total-phosphates", 0.6)["ccme_wqi"] < 100.0
    assert score("water temperature", 32.0, "Cel") is None  # interpretive only
