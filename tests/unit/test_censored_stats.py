"""Kaplan-Meier and ROS for left-censored data: hand-derived values, properties, and simulation.

The simulations are the acceptance criterion: estimators are judged against the KNOWN truth of
seeded synthetic log-normal data (synthetic test data, not real-world performance).
"""
import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from oah.indices.censored import (
    kaplan_meier_left_censored as km,
    ros_left_censored as ros,
    summarize_censored,
)


def test_km_without_censoring_equals_sample_statistics():
    result = km([1, 2, 3, 4], [False] * 4)
    assert (result.mean, result.median, result.n_censored) == (2.5, 2.5, 0)
    odd = km([5, 1, 3], [False] * 3)
    assert (odd.mean, odd.median) == (3.0, 3.0)


def test_km_hand_derived_case_with_one_non_detect():
    # values 2, <3, 4, 5. Flipped (M=5): S falls to .75 at 0, .5 at 1, 0 at 3 -> mean_y 1.75, median_y 2.
    result = km([2, 3, 4, 5], [False, True, False, False])
    assert result.mean == pytest.approx(3.25)
    assert result.median == pytest.approx(3.0)
    assert not result.smallest_treated_as_detect


def test_km_smallest_censored_is_treated_as_detect_and_flagged():
    result = km([1, 2, 3, 4], [True, False, False, False])
    assert result.smallest_treated_as_detect
    assert (result.mean, result.median) == (2.5, 2.5)


def test_km_single_limit_mean_equals_substitution_by_the_limit_documented_bias():
    values, cens = [0.5, 0.5, 2.0, 3.0, 4.0], [True, True, False, False, False]
    assert km(values, cens).mean == pytest.approx(sum(values) / len(values))


@pytest.mark.parametrize(
    ("values", "cens"),
    [
        ([], []),
        ([1, 2], [False]),
        ([1.0, 2.0], [True, True]),
        ([1.0, math.nan], [False, False]),
        ([1.0, math.inf], [False, False]),
        ([True, 2.0], [False, False]),
    ],
)
def test_km_and_ros_reject_invalid_input(values, cens):
    with pytest.raises(ValueError):
        km(values, cens)
    with pytest.raises(ValueError):
        ros(values, cens)


def test_ros_without_censoring_returns_the_exact_sample_mean_and_median():
    result = ros([1.0, 2.0, 4.0, 8.0], [False] * 4)
    assert (result.mean, result.median) == (3.75, 3.0)


@pytest.mark.parametrize(
    ("values", "cens"),
    [
        ([1.0, 1.0, 1.0, 0.5], [False, False, False, True]),
        ([0.0, 1.0, 2.0, 3.0], [False] * 4),
        ([5, 5, 5, 5], [False] * 4),
    ],
)
def test_ros_refuses_what_it_cannot_fit(values, cens):
    with pytest.raises(ValueError, match="ROS needs"):
        ros(values, cens)


def test_ros_imputes_below_the_limit_and_keeps_detects():
    values = [0.5, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0]
    cens = [True, True] + [False] * 5
    result = ros(values, cens)
    assert result.n_censored == 2
    # imputed values come from a fitted line, so the mean sits below the substitution-by-limit mean
    assert result.mean < sum(values) / len(values)


@given(
    st.lists(st.tuples(st.floats(0.01, 1000, allow_nan=False), st.booleans()), min_size=2, max_size=40),
    st.randoms(use_true_random=False),
)
@settings(max_examples=150, deadline=None)
def test_km_is_bounded_and_permutation_invariant(pairs, rnd):
    if all(c for _, c in pairs):
        pairs[0] = (pairs[0][0], False)
    values, cens = [v for v, _ in pairs], [c for _, c in pairs]
    result = km(values, cens)
    assert min(values) - 1e-9 <= result.median <= max(values) + 1e-9
    assert min(values) - 1e-9 <= result.mean <= max(values) + 1e-9
    shuffled = pairs[:]
    rnd.shuffle(shuffled)
    again = km([v for v, _ in shuffled], [c for _, c in shuffled])
    assert again.mean == pytest.approx(result.mean) and again.median == pytest.approx(result.median)


# --- simulation against known truth (seeded, deterministic) -------------------------------------

TRUE_MEAN, TRUE_MEDIAN = math.exp(0.5), 1.0  # lognormal(mu=0, sigma=1)


def _bias(limits, n=300, reps=60, seed=5):
    rng = np.random.default_rng(seed)
    acc = {k: [] for k in ("ros_mean", "ros_med", "km_mean", "km_med", "half_med")}
    for _ in range(reps):
        x = rng.lognormal(0, 1, n)
        dl = rng.choice(limits, n)
        c = x < dl
        v = np.where(c, dl, x)
        r, k = ros(list(v), list(c)), km(list(v), list(c))
        acc["ros_mean"].append(r.mean - TRUE_MEAN)
        acc["ros_med"].append(r.median - TRUE_MEDIAN)
        acc["km_mean"].append(k.mean - TRUE_MEAN)
        acc["km_med"].append(k.median - TRUE_MEDIAN)
        acc["half_med"].append(float(np.median(np.where(c, dl / 2, v))) - TRUE_MEDIAN)
    return {name: float(np.mean(values)) for name, values in acc.items()}


def test_simulation_km_median_and_ros_mean_are_nearly_unbiased_with_mixed_limits():
    bias = _bias([0.2, 0.8, 1.6])
    assert abs(bias["km_med"]) < 0.05 and abs(bias["ros_mean"]) < 0.06 and abs(bias["ros_med"]) < 0.06
    assert bias["half_med"] < -0.10, "substitution by half the limit must be visibly worse for the median"


def test_simulation_km_mean_is_biased_upward_at_half_censoring_but_ros_is_not():
    bias = _bias([1.0])  # about 50% of a lognormal(0,1) lies below 1
    assert bias["km_mean"] > 0.15, "documented limitation of the Kaplan-Meier mean"
    assert abs(bias["ros_mean"]) < 0.06


# --- recommended summary ------------------------------------------------------------------------


def test_summary_uses_km_median_and_ros_mean_and_reports_km_mean_separately():
    values = [0.5, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 9.0, 10.0, 12.0]
    cens = [True, True] + [False] * 8
    report = summarize_censored(values, cens)
    assert (report.median_method, report.mean_method) == ("kaplan-meier", "ros-lognormal")
    assert report.median == km(values, cens).median and report.mean == ros(values, cens).mean
    assert report.km_mean == km(values, cens).mean
    assert any(w.startswith("small-sample") for w in report.warnings)


def test_summary_falls_back_to_km_mean_when_ros_is_not_applicable_and_warns():
    report = summarize_censored([0.5, 2.0, 4.0], [True, False, False])
    assert report.mean_method == "kaplan-meier"
    assert any(w.startswith("ros-not-applicable") for w in report.warnings)


def test_summary_without_censoring_is_plain_and_high_censoring_is_flagged():
    plain = summarize_censored([float(i) for i in range(1, 31)], [False] * 30)
    assert plain.mean_method == "sample-mean" and plain.warnings == ()
    heavy = summarize_censored(
        [1.0] * 20 + [2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0], [True] * 20 + [False] * 10
    )
    assert any(w.startswith("high-censoring") for w in heavy.warnings)
