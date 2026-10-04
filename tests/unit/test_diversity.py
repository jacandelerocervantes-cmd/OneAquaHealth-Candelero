"""Unit and property tests for ecological diversity and richness estimators."""

import math
import pytest
from hypothesis import given, strategies as st

from oah.indices.diversity import chao1, pielou, shannon, simpson


def test_diversity_indices_hand_computed_example():
    # Hand calculation:
    # Sample counts: {"A": 10, "B": 30, "C": 60}, Total N = 100, S = 3
    # p_A = 0.10, p_B = 0.30, p_C = 0.60
    # Shannon H' = -(0.10 * ln(0.10) + 0.30 * ln(0.30) + 0.60 * ln(0.60))
    #   ln(0.10) = -2.302585093 -> -0.230258509
    #   ln(0.30) = -1.203972804 -> -0.361191841
    #   ln(0.60) = -0.510825624 -> -0.306495374
    # H' = 0.897945724
    #
    # Simpson D = 1 - (0.10^2 + 0.30^2 + 0.60^2) = 1 - (0.01 + 0.09 + 0.36) = 1 - 0.46 = 0.54
    #
    # Pielou J' = H' / ln(3) = 0.897945724 / 1.098612289 = 0.817345375
    sample = {"A": 10, "B": 30, "C": 60}

    expected_shannon = -(0.10 * math.log(0.10) + 0.30 * math.log(0.30) + 0.60 * math.log(0.60))
    assert shannon(sample) == pytest.approx(expected_shannon)

    assert simpson(sample) == pytest.approx(0.54)

    expected_pielou = expected_shannon / math.log(3)
    assert pielou(sample) == pytest.approx(expected_pielou)


def test_single_species_sample():
    single_sample = {"Baetidae": 50}
    assert shannon(single_sample) == 0.0
    assert simpson(single_sample) == 0.0
    with pytest.raises(ValueError, match="at least 2 distinct species"):
        pielou(single_sample)


def test_chao1_hand_computed_examples():
    # Hand calculation 1 (with doubletons f2 > 0):
    # S_obs = 10, f1 = 4 (singletons), f2 = 2 (doubletons)
    # S_Chao1 = 10 + (4 * 3) / (2 * (2 + 1)) = 10 + 12 / 6 = 12.0
    val_with_f2 = chao1(10, 4, 2)
    assert val_with_f2 == pytest.approx(12.0)

    # Hand calculation 2 (zero doubletons f2 == 0 branch):
    # S_obs = 10, f1 = 4, f2 = 0
    # S_Chao1 = 10 + (4 * 3) / (2 * (0 + 1)) = 10 + 12 / 2 = 16.0
    val_zero_f2 = chao1(10, 4, 0)
    assert val_zero_f2 == pytest.approx(16.0)


@given(
    st.dictionaries(
        keys=st.text(min_size=1, max_size=5),
        values=st.integers(min_value=0, max_value=1000),
        min_size=1,
        max_size=10,
    )
)
def test_property_shannon_non_negative_and_simpson_in_unit_range(counts):
    h_val = shannon(counts)
    d_val = simpson(counts)
    assert h_val >= 0.0
    assert 0.0 <= d_val < 1.0


@given(
    s_obs=st.integers(min_value=0, max_value=1000),
    f1=st.integers(min_value=0, max_value=500),
    f2=st.integers(min_value=0, max_value=500),
)
def test_property_chao1_at_least_observed_richness(s_obs, f1, f2):
    chao_val = chao1(s_obs, f1, f2)
    assert chao_val >= float(s_obs)
