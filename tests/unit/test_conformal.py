"""Unit and property tests for split conformal classification."""

import numpy as np
import pytest

from oah.synthetic.campaign import generate_campaign
from oah.synthetic.fhir import build_synthetic_batch, rebuild_annotation_table
from oah.uncertainty.conformal import (
    assert_disjoint_specimens,
    compute_calibration_quantile,
    compute_ece,
    compute_posterior_probabilities,
    compute_risk_coverage_curve,
    predict_conformal_set,
)

SITE_LABELS = ("Loc-Almyros", "Loc-Benevento", "Loc-OS")


def test_finite_sample_quantile_tiny_hand_computed_example():
    scores = [0.1, 0.2, 0.3, 0.4, 0.5]
    cutoff = compute_calibration_quantile(scores, alpha=0.2)
    assert cutoff == pytest.approx(0.5)


def test_empirical_coverage_across_thirty_seeds_meets_lower_bound():
    alphas = (0.05, 0.10, 0.20)
    results = {a: [] for a in alphas}
    for i in range(30):
        cal_seed = 1000 + i
        test_seed = 2000 + i
        cal_camp = generate_campaign(cal_seed, SITE_LABELS, observer_count=8, specimens_per_site=70, annotators_per_specimen=5)
        cal_batch = build_synthetic_batch(cal_camp)
        cal_ann = rebuild_annotation_table(cal_batch.records)
        raw_cal_post, _cal_provider = compute_posterior_probabilities(cal_ann, cal_camp.taxa_families)
        cal_true = {f"cal_s{cal_seed}_{spec.specimen_id}": spec.true_family for spec in cal_camp.specimens}
        cal_post = {f"cal_s{cal_seed}_{spec_id}": post for spec_id, post in raw_cal_post.items()}
        cal_scores = [1.0 - cal_post[spec_id][true_c] for spec_id, true_c in cal_true.items()]

        test_camp = generate_campaign(test_seed, SITE_LABELS, observer_count=8, specimens_per_site=70, annotators_per_specimen=5)
        test_batch = build_synthetic_batch(test_camp)
        test_ann = rebuild_annotation_table(test_batch.records)
        raw_test_post, test_provider = compute_posterior_probabilities(test_ann, test_camp.taxa_families)
        test_true = {f"test_s{test_seed}_{spec.specimen_id}": spec.true_family for spec in test_camp.specimens}
        test_post = {f"test_s{test_seed}_{spec_id}": post for spec_id, post in raw_test_post.items()}

        assert_disjoint_specimens(cal_true, test_true)

        for alpha in alphas:
            q_cutoff = compute_calibration_quantile(cal_scores, alpha)
            sets = [
                predict_conformal_set(test_post[sid], q_cutoff, provider=test_provider, specimen_id=sid)
                for sid in test_true
            ]
            cov = float(np.mean([1.0 if test_true[s.specimen_id] in s.prediction_set else 0.0 for s in sets]))
            results[alpha].append(cov)

    for alpha in alphas:
        mean_cov = float(np.mean(results[alpha]))
        assert mean_cov >= (1.0 - alpha) - 0.03


def test_empty_and_too_small_calibration_sets_raise_value_error():
    with pytest.raises(ValueError, match="smaller than required minimum"):
        compute_calibration_quantile([], alpha=0.1)

    with pytest.raises(ValueError, match="smaller than required minimum"):
        compute_calibration_quantile([0.1, 0.2, 0.3], alpha=0.1)


def test_calibration_and_test_specimen_disjointness_enforced():
    cal_true = {"SPEC-01": "Baetidae", "SPEC-02": "Heptageniidae"}
    overlapping_test_true = {"SPEC-02": "Heptageniidae", "SPEC-03": "Gammaridae"}

    with pytest.raises(ValueError, match="not disjoint"):
        assert_disjoint_specimens(cal_true, overlapping_test_true)

    disjoint_test_true = {"SPEC-03": "Gammaridae", "SPEC-04": "Leuctridae"}
    assert_disjoint_specimens(cal_true, disjoint_test_true)


def test_predict_conformal_set_raises_type_error_if_provider_omitted():
    probs = {"Baetidae": 0.80, "Heptageniidae": 0.20}
    with pytest.raises(TypeError):
        predict_conformal_set(probs, 0.25)


def test_predict_conformal_set_records_explicit_provider():
    probs = {"Baetidae": 0.80, "Heptageniidae": 0.20}
    pset = predict_conformal_set(probs, 0.25, provider="majority-vote-smoothed", specimen_id="SPEC-P1")
    assert pset.probability_provider == "majority-vote-smoothed"
    assert pset.specimen_id == "SPEC-P1"


def test_compute_risk_coverage_curve_hand_computed():
    posteriors = [
        {"A": 0.9, "B": 0.1},
        {"A": 0.7, "B": 0.3},
        {"A": 0.4, "B": 0.6},
        {"A": 0.55, "B": 0.45},
    ]
    true_labels = ["A", "B", "B", "A"]
    thresholds = [0.5, 0.65, 0.8, 0.95]

    curve = compute_risk_coverage_curve(posteriors, true_labels, thresholds)
    assert len(curve) == 4

    assert curve[0].threshold == pytest.approx(0.5)
    assert curve[0].coverage == pytest.approx(1.0)
    assert curve[0].risk == pytest.approx(0.25)

    assert curve[1].threshold == pytest.approx(0.65)
    assert curve[1].coverage == pytest.approx(0.50)
    assert curve[1].risk == pytest.approx(0.50)

    assert curve[2].threshold == pytest.approx(0.8)
    assert curve[2].coverage == pytest.approx(0.25)
    assert curve[2].risk == pytest.approx(0.0)

    assert curve[3].threshold == pytest.approx(0.95)
    assert curve[3].coverage == pytest.approx(0.0)
    assert curve[3].risk == pytest.approx(0.0)


def test_compute_ece_calculation():
    posteriors = [
        {"A": 0.9, "B": 0.1},
        {"A": 0.8, "B": 0.2},
    ]
    true_labels = ["A", "A"]
    ece = compute_ece(posteriors, true_labels, num_bins=5)
    assert ece >= 0.0
