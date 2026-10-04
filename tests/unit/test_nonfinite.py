"""NaN and infinity must never be scored: the CCME WQI used to return 100.0 (Excellent) for them.

Regression for the 2026-09-26 audit finding. Comparisons with NaN are always false, so a NaN value
counted as a pass; an infinite value made F3 NaN and ``min(100, nan)`` returned 100. Synthetic
inputs only, no network.
"""
import math

import pytest

from oah.indices.apply_to_sandbox import apply_ccme_wqi_to_sandbox
from oah.indices.water_parameter_limits import exact_numeric_value, is_physically_possible
from oah.indices.water_quality import ccme_wqi, eqr, excursion

PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"
NON_FINITE = [math.nan, math.inf, -math.inf]


def _plain(oid, param_code, value, site="Location/S1"):
    return {
        "resourceType": "Observation",
        "id": oid,
        "meta": {"profile": [PROFILE]},
        "subject": {"reference": site},
        "code": {"coding": [{"code": param_code}]},
        "valueQuantity": {"value": value, "system": "http://unitsofmeasure.org", "code": "mg/L"},
    }


@pytest.mark.parametrize("bad", NON_FINITE)
def test_excursion_rejects_non_finite_observed(bad):
    with pytest.raises(ValueError, match="finite"):
        excursion(bad, 5.0, False)


@pytest.mark.parametrize("bad", NON_FINITE)
def test_excursion_rejects_non_finite_limit(bad):
    with pytest.raises(ValueError, match="finite"):
        excursion(5.0, bad, True)


@pytest.mark.parametrize("bad", NON_FINITE)
def test_ccme_wqi_rejects_non_finite_instead_of_returning_excellent(bad):
    with pytest.raises(ValueError, match="finite"):
        ccme_wqi([("Nitrate", bad, 50.0, False)])
    with pytest.raises(ValueError, match="finite"):
        ccme_wqi([("Nitrate", 10.0, 50.0, False), ("Nitrate", bad, 50.0, False)])


@pytest.mark.parametrize("bad", NON_FINITE)
def test_eqr_rejects_non_finite(bad):
    with pytest.raises(ValueError, match="finite"):
        eqr(bad, 1.0)
    with pytest.raises(ValueError, match="finite"):
        eqr(0.5, bad)


@pytest.mark.parametrize("bad", NON_FINITE)
def test_exact_numeric_value_is_none_for_non_finite(bad):
    assert exact_numeric_value({"value": bad}) is None


@pytest.mark.parametrize("bad", NON_FINITE)
@pytest.mark.parametrize("parameter", ["pH", "Water temperature", "Nitrate"])
def test_non_finite_is_never_physically_possible(parameter, bad):
    assert is_physically_possible(parameter, bad) is False


@pytest.mark.parametrize("bad", [math.nan, math.inf])
def test_pipeline_excludes_and_counts_a_non_finite_observation(bad):
    result = apply_ccme_wqi_to_sandbox(
        [_plain("good", "nitrate", 10.0), _plain("bad", "nitrate", bad, site="Location/S2")]
    )
    assert result["skipped_non_finite_observations"] == 1
    evaluated = {site["location_ref"]: site for site in result["evaluated_locations"]}
    assert "Location/S2" not in evaluated  # the corrupt value is not scored, never "Excellent"
    assert evaluated["Location/S1"]["ccme_wqi"] == 100.0


def test_pipeline_counts_zero_when_every_value_is_finite():
    result = apply_ccme_wqi_to_sandbox([_plain("ok", "nitrate", 10.0)])
    assert result["skipped_non_finite_observations"] == 0


from hypothesis import given, strategies as st  # noqa: E402


@given(
    observed=st.floats(allow_nan=True, allow_infinity=True),
    limit=st.floats(min_value=0.001, max_value=1e6),
    is_lower=st.booleans(),
)
def test_ccme_wqi_is_finite_in_range_or_raises_for_any_float(observed, limit, is_lower):
    if not math.isfinite(observed):
        with pytest.raises(ValueError, match="finite"):
            ccme_wqi([("Any", observed, limit, is_lower)])
    else:
        score = ccme_wqi([("Any", observed, limit, is_lower)])
        assert 0.0 <= score <= 100.0 and math.isfinite(score)
