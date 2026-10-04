from hypothesis import given, strategies as st
from oah.qc.statistics import check_range, check_statistics, check_unit, component_statistics

UCUM = {"ug/L"}

def test_statistics_and_range_rules():
    assert not check_statistics({"minimum": 1, "median": 2, "maximum": 3, "average": 2})
    assert {f.code for f in check_statistics({"minimum": 3, "median": 2, "maximum": 4})} == {"statistical-order"}
    assert check_statistics({"minimum": 1, "maximum": 0})[0].code == "statistical-bounds"
    assert {f.code for f in check_statistics({"minimum": 1, "maximum": 3, "average": 4})} == {"mean-range"}
    assert not check_range(2, 1, 3, "x")
    assert check_range(4, 1, 3, "x")[0].code == "physical-range"
    assert not check_range(2, None, 3, "x")
    assert not check_range(2, 1, None, "x")

def test_ucum_and_aluminium_components():
    assert not check_unit({"system": "http://unitsofmeasure.org", "code": "ug/L"}, UCUM)
    assert check_unit({"system": "http://unitsofmeasure.org"}, UCUM)[0].code == "ucum-unit"
    assert check_unit({"system": "bad", "code": "ug/L"}, UCUM)[0].code == "ucum-system"
    def c(name, value): return {"code": {"coding": [{"code": name}]}, "valueQuantity": {"value": value, "system": "http://unitsofmeasure.org", "code": "ug/L"}}
    observation = {"id": "Obs-Almyros-AluminiumDissolved-2013", "component": [c("average", 50000), c("maximum", 100000), c("minimum", 100000), c("median", 10)]}
    findings = component_statistics(observation, UCUM)
    assert {f.code for f in findings} >= {"statistical-order", "mean-range"}
    assert all(f.resource_id == observation["id"] for f in findings if f.code.startswith(("statistical", "mean")))

def test_boolean_component_value_is_ignored():
    observation = {"id": "boolean", "component": [{"code": {"coding": [{"code": "minimum"}]}, "valueQuantity": {"value": True, "system": "http://unitsofmeasure.org", "code": "ug/L"}}]}
    assert not component_statistics(observation, UCUM)

def test_component_findings_always_identify_observation():
    observation = {"id": "identifier", "component": [{"code": {"coding": [{"code": "minimum"}]}, "valueQuantity": {"value": 1, "system": "bad"}}]}
    findings = component_statistics(observation, UCUM)
    assert findings
    assert all(item.resource_id == "identifier" for item in findings)

@given(st.floats(allow_nan=False), st.floats(allow_nan=False), st.floats(allow_nan=False))
def test_ordered_values_never_flagged(a, b, c):
    low, middle, high = sorted((a, b, c))
    assert not check_statistics({"minimum": low, "median": middle, "maximum": high, "average": middle})

@given(st.floats(allow_nan=False), st.floats(allow_nan=False))
def test_inverted_bounds_flagged(a, b):
    if a > b:
        assert check_statistics({"minimum": a, "maximum": b})
