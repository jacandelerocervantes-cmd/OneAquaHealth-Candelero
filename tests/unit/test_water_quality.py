"""Unit and property tests for water quality indices and EQR classification."""

import pytest
from hypothesis import given, strategies as st

from oah.indices.water_quality import ccme_wqi, classify_ccme_wqi, eqr


def test_ccme_wqi_hand_computed_example():
    # Hand calculation:
    # 3 measurements across 2 unique parameters:
    #   1. ("pH", 8.5, 8.0) -> Failed (observed 8.5 > 8.0). Excursion = (8.5 / 8.0) - 1 = 0.0625.
    #   2. ("pH", 7.5, 8.0) -> Passed.
    #   3. ("Nitrate", 12.0, 10.0) -> Failed (observed 12.0 > 10.0). Excursion = (12.0 / 10.0) - 1 = 0.20.
    #
    # Parameters M_v = 2 ("pH", "Nitrate"), Failed u_v = 2 -> F1 = (2 / 2) * 100 = 100.0
    # Total tests M_t = 3, Failed tests u_t = 2 -> F2 = (2 / 3) * 100 = 66.66666666666666
    # Sum excursions = 0.0625 + 0.20 = 0.2625
    # nse = 0.2625 / 3 = 0.0875
    # F3 = 0.0875 / (0.01 * 0.0875 + 0.01) = 0.0875 / 0.010875 = 8.045977011494253
    #
    # Vector norm = sqrt(100^2 + 66.6667^2 + 8.0460^2) = sqrt(10000 + 4444.4444 + 64.7377) = sqrt(14509.1821) = 120.454066
    # Divisor = 1.732 -> 120.454066 / 1.732 = 69.5462276
    # CCME WQI = 100 - 69.5462276 = 30.453772
    measurements = [
        ("pH", 8.5, 8.0),
        ("pH", 7.5, 8.0),
        ("Nitrate", 12.0, 10.0),
    ]
    wqi_score = ccme_wqi(measurements)
    assert wqi_score == pytest.approx(30.453772, abs=1e-4)


def test_ccme_wqi_all_passing_returns_100():
    measurements = [
        ("pH", 7.0, 8.0),
        ("Nitrate", 5.0, 10.0),
    ]
    assert ccme_wqi(measurements) == pytest.approx(100.0)


def test_ccme_wqi_empty_measurements_raises_value_error():
    with pytest.raises(ValueError, match="cannot be empty"):
        ccme_wqi([])


def test_eqr_class_boundaries():
    # High: >= 0.8
    r, c = eqr(0.85, 1.0)
    assert r == pytest.approx(0.85)
    assert c == "High"

    r_boundary_high, c_boundary_high = eqr(0.80, 1.0)
    assert c_boundary_high == "High"

    # Good: [0.6, 0.8)
    r_good, c_good = eqr(0.79, 1.0)
    assert c_good == "Good"

    r_boundary_good, c_boundary_good = eqr(0.60, 1.0)
    assert c_boundary_good == "Good"

    # Moderate: [0.4, 0.6)
    r_mod, c_mod = eqr(0.55, 1.0)
    assert c_mod == "Moderate"

    r_boundary_mod, c_boundary_mod = eqr(0.40, 1.0)
    assert c_boundary_mod == "Moderate"

    # Poor: [0.2, 0.4)
    r_poor, c_poor = eqr(0.35, 1.0)
    assert c_poor == "Poor"

    r_boundary_poor, c_boundary_poor = eqr(0.20, 1.0)
    assert c_boundary_poor == "Poor"

    # Bad: [0.0, 0.2)
    r_bad, c_bad = eqr(0.10, 1.0)
    assert c_bad == "Bad"


def test_classify_ccme_wqi_band_boundaries():
    assert classify_ccme_wqi(100.0) == "Excellent"
    assert classify_ccme_wqi(95.0) == "Excellent"
    assert classify_ccme_wqi(94.999) == "Good"
    assert classify_ccme_wqi(80.0) == "Good"
    assert classify_ccme_wqi(79.999) == "Fair"
    assert classify_ccme_wqi(65.0) == "Fair"
    assert classify_ccme_wqi(64.999) == "Marginal"
    assert classify_ccme_wqi(45.0) == "Marginal"
    assert classify_ccme_wqi(44.999) == "Poor"
    assert classify_ccme_wqi(0.0) == "Poor"


def test_classify_ccme_wqi_rejects_out_of_range_scores():
    with pytest.raises(ValueError):
        classify_ccme_wqi(-0.01)
    with pytest.raises(ValueError):
        classify_ccme_wqi(100.01)


def test_eqr_invalid_inputs_raise_value_error():
    with pytest.raises(ValueError, match="strictly positive"):
        eqr(1.0, 0.0)

    with pytest.raises(ValueError, match="cannot be negative"):
        eqr(-1.0, 1.0)


@given(
    st.lists(
        st.tuples(
            st.sampled_from(["pH", "Nitrate", "Phosphate", "dissolved_oxygen"]),
            st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False),
            st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False),
        ),
        min_size=1,
        max_size=20,
    )
)
def test_property_ccme_wqi_always_in_zero_to_hundred_range(measurements):
    wqi = ccme_wqi(measurements)
    assert 0.0 <= wqi <= 100.0
