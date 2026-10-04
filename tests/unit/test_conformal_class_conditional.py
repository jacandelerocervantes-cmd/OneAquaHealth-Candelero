"""Class-conditional (Mondrian) conformal prediction over consensus posteriors.

All data here is synthetic: results measure the simulator and the method, not real ecology.
"""
import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from oah.synthetic.campaign import generate_campaign
from oah.synthetic.fhir import build_synthetic_batch, rebuild_annotation_table
from oah.uncertainty.conformal import (
    calibrate_class_conditional,
    compute_calibration_quantile,
    compute_posterior_probabilities,
    coverage_by_class,
    predict_class_conditional_set,
    predict_conformal_set,
    set_size_summary,
)


def _post(p_a):
    return {"A": p_a, "B": 1.0 - p_a}


def test_calibration_picks_the_finite_sample_quantile_per_class():
    # class A scores 1-p(A) = .1,.2,.3,.4 ; class B scores .5,.6,.7,.8 ; alpha .5 -> k = ceil(5*.5) = 3
    posteriors = {f"a{i}": _post(1 - s) for i, s in enumerate([0.1, 0.2, 0.3, 0.4])}
    posteriors |= {f"b{i}": {"A": s, "B": 1 - s} for i, s in enumerate([0.5, 0.6, 0.7, 0.8])}
    truth = {f"a{i}": "A" for i in range(4)} | {f"b{i}": "B" for i in range(4)}
    calibration = calibrate_class_conditional(posteriors, truth, ["A", "B"], alpha=0.5)
    assert calibration.quantiles == pytest.approx({"A": 0.3, "B": 1 - 0.3})
    assert calibration.class_counts == {"A": 4, "B": 4} and calibration.uncalibrated_classes == ()


def test_prediction_uses_each_class_own_cutoff():
    posteriors = {f"a{i}": _post(1 - s) for i, s in enumerate([0.1, 0.2, 0.3, 0.4])}
    posteriors |= {f"b{i}": {"A": s, "B": 1 - s} for i, s in enumerate([0.5, 0.6, 0.7, 0.8])}
    truth = {f"a{i}": "A" for i in range(4)} | {f"b{i}": "B" for i in range(4)}
    calibration = calibrate_class_conditional(posteriors, truth, ["A", "B"], alpha=0.5)
    # p(A)=.6, p(B)=.4: A needs 1-.6=.4 <= .3 (no); B needs 1-.4=.6 <= .7 (yes) -> {B}
    result = predict_class_conditional_set(_post(0.6), calibration, "test", "s1")
    assert result.prediction_set == ("B",)
    assert result.class_quantiles == pytest.approx({"A": 0.3, "B": 0.7}) and result.specimen_id == "s1"
    # a marginal cutoff of .5 would have returned {A}: the per-class rule differs
    assert predict_conformal_set(_post(0.6), 0.5, "test").prediction_set == ("A",)


def test_class_with_too_few_examples_is_rejected_by_default_and_flagged_when_included():
    posteriors = {f"a{i}": _post(0.9) for i in range(30)} | {"b0": _post(0.2)}
    truth = {f"a{i}": "A" for i in range(30)} | {"b0": "B"}
    with pytest.raises(ValueError, match="fewer than ceil"):
        calibrate_class_conditional(posteriors, truth, ["A", "B"], alpha=0.1)
    calibration = calibrate_class_conditional(posteriors, truth, ["A", "B"], alpha=0.1, on_insufficient="include")
    assert calibration.uncalibrated_classes == ("B",) and calibration.quantiles["B"] == 1.0
    # cutoff 1.0 puts B in every set: the price of an uncalibrated class
    assert "B" in predict_class_conditional_set(_post(0.99), calibration, "t").prediction_set


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"alpha": 0.0}, "alpha"),
        ({"alpha": 1.0}, "alpha"),
        ({"alpha": 0.1, "on_insufficient": "ignore"}, "on_insufficient"),
        ({"alpha": 0.1, "classes": ["A"]}, "at least two"),
        ({"alpha": 0.1, "classes": ["A", "A"]}, "at least two"),
    ],
)
def test_calibration_validates_its_arguments(kwargs, match):
    args = {"posteriors": {"x": _post(0.5)}, "true_labels": {"x": "A"}, "classes": ["A", "B"]} | kwargs
    with pytest.raises(ValueError, match=match):
        calibrate_class_conditional(**args)


def test_calibration_rejects_unknown_labels_and_missing_posteriors():
    with pytest.raises(ValueError, match="not in classes"):
        calibrate_class_conditional({"x": _post(0.5)}, {"x": "C"}, ["A", "B"], 0.1)
    with pytest.raises(ValueError, match="No posterior"):
        calibrate_class_conditional({}, {"x": "A"}, ["A", "B"], 0.1)


def test_prediction_rejects_classes_without_a_cutoff():
    calibration = calibrate_class_conditional(
        {f"a{i}": _post(0.9) for i in range(10)} | {f"b{i}": _post(0.1) for i in range(10)},
        {f"a{i}": "A" for i in range(10)} | {f"b{i}": "B" for i in range(10)},
        ["A", "B"],
        0.1,
    )
    with pytest.raises(ValueError, match="without a calibrated cutoff"):
        predict_class_conditional_set({"A": 0.5, "C": 0.5}, calibration, "t")


def test_coverage_and_size_summaries():
    sets = [("A",), ("A", "B"), (), ("B",)]
    truth = ["A", "B", "B", "A"]
    assert coverage_by_class(sets, truth) == {"A": (0.5, 2), "B": (0.5, 2)}
    assert set_size_summary(sets) == {"empty_rate": 0.25, "singleton_rate": 0.5, "ambiguous_rate": 0.25, "mean_size": 1.0}
    assert set_size_summary([])["mean_size"] == 0.0
    with pytest.raises(ValueError):
        coverage_by_class([("A",)], ["A", "B"])


@given(
    st.lists(st.floats(0.0, 1.0), min_size=12, max_size=40),
    st.lists(st.floats(0.0, 1.0), min_size=12, max_size=40),
    st.floats(0.05, 0.5),
)
@settings(max_examples=100, deadline=None)
def test_higher_alpha_never_enlarges_a_class_conditional_set(a_scores, b_scores, alpha):
    posteriors = {f"a{i}": _post(1 - s) for i, s in enumerate(a_scores)}
    posteriors |= {f"b{i}": {"A": s, "B": 1 - s} for i, s in enumerate(b_scores)}
    truth = {f"a{i}": "A" for i in range(len(a_scores))} | {f"b{i}": "B" for i in range(len(b_scores))}
    tight = calibrate_class_conditional(posteriors, truth, ["A", "B"], alpha, on_insufficient="include")
    loose = calibrate_class_conditional(posteriors, truth, ["A", "B"], min(alpha + 0.2, 0.95), on_insufficient="include")
    for p_a in (0.0, 0.3, 0.5, 0.8, 1.0):
        assert set(predict_class_conditional_set(_post(p_a), loose, "t").prediction_set) <= set(
            predict_class_conditional_set(_post(p_a), tight, "t").prediction_set
        )


# --- why the class-conditional version exists: a constructed scenario ---------------------------


def _hard_class_data(rng, n):
    truth = np.where(rng.random(n) < 0.2, "B", "A")
    p_true = np.where(
        truth == "A",
        np.clip(rng.normal(0.92, 0.05, n), 0.01, 0.999),  # class A: the model is confident and right
        np.clip(rng.normal(0.55, 0.20, n), 0.01, 0.999),  # class B: the model is unsure
    )
    posteriors = [{str(t): float(p), ("B" if t == "A" else "A"): float(1 - p)} for t, p in zip(truth, p_true)]
    return posteriors, [str(t) for t in truth]


def test_marginal_conformal_undercovers_the_hard_class_but_class_conditional_does_not():
    alpha, rng = 0.1, np.random.default_rng(3)
    cal_post, cal_true = _hard_class_data(rng, 2000)
    posteriors = {str(i): p for i, p in enumerate(cal_post)}
    labels = {str(i): t for i, t in enumerate(cal_true)}
    marginal_q = compute_calibration_quantile([1 - posteriors[i][labels[i]] for i in posteriors], alpha)
    calibration = calibrate_class_conditional(posteriors, labels, ["A", "B"], alpha)

    test_post, test_true = _hard_class_data(rng, 20000)
    marginal = coverage_by_class([predict_conformal_set(p, marginal_q, "t").prediction_set for p in test_post], test_true)
    conditional = coverage_by_class(
        [predict_class_conditional_set(p, calibration, "t").prediction_set for p in test_post], test_true
    )
    assert marginal["B"][0] < 0.7, "marginal coverage hides a badly served class"
    assert marginal["A"][0] > 0.97
    assert conditional["A"][0] >= 0.86 and conditional["B"][0] >= 0.86


# --- on the project's own simulator with Dawid-Skene posteriors ---------------------------------

SITES = ("Loc-Almyros", "Loc-Benevento", "Loc-OS")


def _campaign(seed):
    campaign = generate_campaign(seed, SITES, observer_count=8, specimens_per_site=70, annotators_per_specimen=5)
    annotations = rebuild_annotation_table(build_synthetic_batch(campaign).records)
    posteriors, provider = compute_posterior_probabilities(annotations, campaign.taxa_families)
    truth = {s.specimen_id: s.true_family for s in campaign.specimens}
    return campaign.taxa_families, posteriors, truth, provider


def test_per_class_coverage_holds_on_dawid_skene_posteriors_of_the_simulator():
    alpha = 0.1
    families, cal_post, cal_true, provider = None, {}, {}, None
    for seed in range(1000, 1006):
        families, post, truth, provider = _campaign(seed)
        cal_post |= {f"{seed}:{k}": v for k, v in post.items()}
        cal_true |= {f"{seed}:{k}": v for k, v in truth.items()}
    calibration = calibrate_class_conditional(cal_post, cal_true, families, alpha)
    sets, truths = [], []
    for seed in range(2000, 2012):
        _, post, truth, _ = _campaign(seed)
        for specimen_id, true_family in truth.items():
            sets.append(predict_class_conditional_set(post[specimen_id], calibration, provider).prediction_set)
            truths.append(true_family)
    coverage = coverage_by_class(sets, truths)
    assert set(coverage) == set(families)
    assert all(value >= 0.86 for value, _ in coverage.values()), coverage
