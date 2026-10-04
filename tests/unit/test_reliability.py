"""Unit and property tests for Dawid-Skene observer reliability estimation."""

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from oah.reliability.dawid_skene import majority_vote, recommend_method, run_dawid_skene
from oah.reliability.eval import evaluate_reliability
from oah.synthetic.campaign import generate_campaign
from oah.synthetic.fhir import build_synthetic_batch, rebuild_annotation_table

SITE_LABELS = ("Loc-Almyros", "Loc-Benevento", "Loc-OS")
TEST_SEEDS = (42, 43, 44, 45, 46, 47, 48, 49, 50, 51)
MONOTONICITY_SEEDS = tuple(range(200, 230))  # 30 fixed seeds: 200..229


def _campaign(seed=42, specimens_per_site=15, annotators_per_specimen=3):
    return generate_campaign(
        seed=seed,
        site_ids=SITE_LABELS,
        observer_count=8,
        specimens_per_site=specimens_per_site,
        annotators_per_specimen=annotators_per_specimen,
    )


def test_map_objective_is_monotonic_non_decreasing_across_thirty_seeds_in_both_regimes():
    for seed in MONOTONICITY_SEEDS:
        for spec, ann in ((15, 3), (70, 5)):
            camp = _campaign(seed=seed, specimens_per_site=spec, annotators_per_specimen=ann)
            batch = build_synthetic_batch(camp)
            annotations = rebuild_annotation_table(batch.records)
            result = run_dawid_skene(annotations, camp.taxa_families, smoothing=1.0)
            trace = result.map_objective_trace
            for t in range(1, len(trace)):
                assert trace[t] >= trace[t - 1] - 1e-7


@given(st.integers(min_value=1, max_value=100))
@settings(max_examples=10)
def test_hypothesis_property_map_objective_is_monotonic_non_decreasing(seed):
    camp = generate_campaign(seed, SITE_LABELS, observer_count=4, specimens_per_site=5, annotators_per_specimen=2)
    batch = build_synthetic_batch(camp)
    annotations = rebuild_annotation_table(batch.records)
    res = run_dawid_skene(annotations, camp.taxa_families, smoothing=1.0)
    trace = res.map_objective_trace
    for t in range(1, len(trace)):
        assert trace[t] >= trace[t - 1] - 1e-7


def test_plain_log_likelihood_is_monotonic_non_decreasing_without_smoothing():
    campaign = _campaign()
    batch = build_synthetic_batch(campaign)
    annotations = rebuild_annotation_table(batch.records)
    result = run_dawid_skene(annotations, campaign.taxa_families, smoothing=0.0)
    trace = result.log_likelihood_trace
    for t in range(1, len(trace)):
        assert trace[t] >= trace[t - 1] - 1e-7


def test_posteriors_sum_to_one_per_specimen():
    campaign = _campaign()
    batch = build_synthetic_batch(campaign)
    annotations = rebuild_annotation_table(batch.records)
    result = run_dawid_skene(annotations, campaign.taxa_families)
    for _spec_id, post in result.posteriors.items():
        total_prob = sum(post.values())
        assert total_prob == pytest.approx(1.0, abs=1e-6)


def test_perfect_observers_recover_ground_truth():
    families = ("Baetidae", "Heptageniidae", "Hydropsychidae", "Perlidae")
    annotations = [
        ("specimen-1", "observer-1", "Baetidae"),
        ("specimen-1", "observer-2", "Baetidae"),
        ("specimen-1", "observer-3", "Baetidae"),
        ("specimen-2", "observer-1", "Perlidae"),
        ("specimen-2", "observer-2", "Perlidae"),
        ("specimen-2", "observer-3", "Perlidae"),
    ]
    result = run_dawid_skene(annotations, families)
    assert result.inferred_labels["specimen-1"] == "Baetidae"
    assert result.inferred_labels["specimen-2"] == "Perlidae"


def test_dawid_skene_data_rich_regime_exceeds_majority_vote():
    mv_accs = []
    ds_accs = []
    for seed in TEST_SEEDS:
        camp = _campaign(seed=seed, specimens_per_site=70, annotators_per_specimen=5)
        batch = build_synthetic_batch(camp)
        ann = rebuild_annotation_table(batch.records)
        mv_labels = majority_vote(ann, camp.taxa_families)
        ds_res = run_dawid_skene(ann, camp.taxa_families, smoothing=1.0)
        metrics = evaluate_reliability(camp, ds_res, mv_labels)
        mv_accs.append(metrics["mv_accuracy"])
        ds_accs.append(metrics["ds_accuracy"])
    mean_mv = float(np.mean(mv_accs))
    mean_ds = float(np.mean(ds_accs))
    assert mean_ds >= mean_mv + 0.03


def test_dawid_skene_data_poor_regime_honest_accuracy_bounds():
    # Documents known sample complexity limitation: with insufficient annotations per observer,
    # Dawid-Skene overfits confusion matrix parameters and performs below Majority Vote.
    mv_accs = []
    ds_accs = []
    for seed in TEST_SEEDS:
        camp = _campaign(seed=seed, specimens_per_site=15, annotators_per_specimen=3)
        batch = build_synthetic_batch(camp)
        ann = rebuild_annotation_table(batch.records)
        mv_labels = majority_vote(ann, camp.taxa_families)
        ds_res = run_dawid_skene(ann, camp.taxa_families, smoothing=1.0)
        metrics = evaluate_reliability(camp, ds_res, mv_labels)
        mv_accs.append(metrics["mv_accuracy"])
        ds_accs.append(metrics["ds_accuracy"])
    mean_mv = float(np.mean(mv_accs))
    mean_ds = float(np.mean(ds_accs))
    assert mean_ds < mean_mv
    assert mean_mv - mean_ds <= 0.25


def test_recommend_method_behavior():
    regimes_and_expected = [
        (15, 3, "one-coin"),
        (15, 5, "one-coin"),
        (70, 3, "dawid-skene"),
        (70, 5, "dawid-skene"),
    ]
    for spec, ann, expected in regimes_and_expected:
        camp = _campaign(seed=42, specimens_per_site=spec, annotators_per_specimen=ann)
        batch = build_synthetic_batch(camp)
        annotations = rebuild_annotation_table(batch.records)
        rec, diag = recommend_method(annotations, threshold=50.0)
        assert rec == expected
        assert diag["threshold"] == 50.0
        assert diag["num_observers"] == 8

    with pytest.raises(ValueError, match="cannot be empty"):
        recommend_method([])


def test_validation_errors_raised_on_invalid_inputs():
    classes = ("A", "B")
    with pytest.raises(ValueError, match="cannot be empty"):
        run_dawid_skene([], classes)

    with pytest.raises(ValueError, match="cannot be empty"):
        majority_vote([], classes)

    with pytest.raises(ValueError, match="at least two"):
        run_dawid_skene([("s1", "o1", "A")], ("A",))

    with pytest.raises(ValueError, match="Unknown label"):
        run_dawid_skene([("s1", "o1", "UNKNOWN")], classes)


def test_adversarial_observer_confusion_matrix_learns_swapping():
    campaign = generate_campaign(seed=42, site_ids=SITE_LABELS, observer_count=8, specimens_per_site=25, annotators_per_specimen=3)
    batch = build_synthetic_batch(campaign)
    annotations = rebuild_annotation_table(batch.records)
    adv_obs = [obs for obs in campaign.observers if obs.role == "adversarial"][0]
    result = run_dawid_skene(annotations, campaign.taxa_families)
    cm = result.confusion_matrices[adv_obs.identifier]
    assert cm[0][1] > 0.35
    assert cm[1][0] > 0.35


def test_weak_observer_estimated_diagonal_is_lower_than_standard_observer():
    weak_diags = []
    standard_diags = []
    for seed in (42, 43, 44):
        camp = generate_campaign(seed, SITE_LABELS, observer_count=8, specimens_per_site=15, annotators_per_specimen=3)
        batch = build_synthetic_batch(camp)
        ann = rebuild_annotation_table(batch.records)
        res = run_dawid_skene(ann, camp.taxa_families)
        for obs in camp.observers:
            cm = np.array(res.confusion_matrices[obs.identifier])
            diag_mean = float(np.trace(cm) / len(camp.taxa_families))
            if obs.role == "weak":
                weak_diags.append(diag_mean)
            elif obs.role == "standard":
                standard_diags.append(diag_mean)
    mean_weak = float(np.mean(weak_diags))
    mean_std = float(np.mean(standard_diags))
    assert mean_weak < mean_std


@given(st.integers(min_value=1, max_value=100))
@settings(max_examples=10)
def test_hypothesis_property_posteriors_are_valid_probability_distributions(seed):
    camp = generate_campaign(seed, SITE_LABELS, observer_count=4, specimens_per_site=5, annotators_per_specimen=2)
    batch = build_synthetic_batch(camp)
    ann = rebuild_annotation_table(batch.records)
    res = run_dawid_skene(ann, camp.taxa_families)
    for _spec_id, post in res.posteriors.items():
        probs = list(post.values())
        assert all(p >= 0.0 for p in probs)
        assert sum(probs) == pytest.approx(1.0, abs=1e-5)
