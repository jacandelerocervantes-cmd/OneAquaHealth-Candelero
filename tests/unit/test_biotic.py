"""Unit and property tests for biotic ecological indices."""

import pytest
from hypothesis import given, strategies as st

from oah.indices.biotic import aspt, bmwp, ept_ratio


def test_bmwp_and_aspt_hand_computed_example():
    # Hand calculation:
    # Taxa present:
    #   - Baetidae: tolerance score 4
    #   - Heptageniidae: tolerance score 10
    #   - Hydropsychidae: tolerance score 5
    #   - Perlidae: tolerance score 10
    # BMWP = 4 + 10 + 5 + 10 = 29
    # Family count = 4
    # ASPT = 29 / 4 = 7.25
    sample_scores = {
        "Baetidae": 4,
        "Heptageniidae": 10,
        "Hydropsychidae": 5,
        "Perlidae": 10,
    }
    calculated_bmwp = bmwp(sample_scores)
    assert calculated_bmwp == 29

    calculated_aspt = aspt(calculated_bmwp, len(sample_scores))
    assert calculated_aspt == pytest.approx(7.25)


def test_aspt_zero_family_count_raises_value_error():
    with pytest.raises(ValueError, match="positive integer"):
        aspt(29, 0)


def test_ept_ratio_hand_computed_example():
    # Hand calculation:
    #   - Ephemeroptera: 20
    #   - Plecoptera: 10
    #   - Trichoptera: 30
    #   - Diptera: 40
    # Total = 20 + 10 + 30 + 40 = 100
    # EPT sum = 20 + 10 + 30 = 60
    # EPT ratio = 60 / 100 = 0.60
    order_counts = {
        "Ephemeroptera": 20,
        "Plecoptera": 10,
        "Trichoptera": 30,
        "Diptera": 40,
    }
    ratio = ept_ratio(order_counts)
    assert ratio == pytest.approx(0.60)


def test_ept_ratio_zero_total_raises_value_error():
    with pytest.raises(ValueError, match="greater than zero"):
        ept_ratio({"Ephemeroptera": 0, "Diptera": 0})


@given(
    st.dictionaries(
        keys=st.text(min_size=1, max_size=10),
        values=st.integers(min_value=1, max_value=10),
        min_size=1,
        max_size=20,
    )
)
def test_property_aspt_bounded_by_min_and_max_tolerance_scores(scores):
    score_sum = bmwp(scores)
    count = len(scores)
    aspt_val = aspt(score_sum, count)
    min_score = min(scores.values())
    max_score = max(scores.values())
    assert min_score <= aspt_val <= max_score
