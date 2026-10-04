"""One-coin Dawid-Skene: correctness, MAP monotonicity, and direction of the measured advantages.

Synthetic data only: results measure the simulator and the estimator, not real ecology.
"""
import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from oah.reliability import majority_vote, run_dawid_skene, run_one_coin
from oah.synthetic.campaign import generate_campaign
from oah.synthetic.fhir import build_synthetic_batch, rebuild_annotation_table
from oah.uncertainty.conformal import compute_ece, compute_posterior_probabilities

SITES = ("Loc-Almyros", "Loc-Benevento", "Loc-OS")
CLASSES = ("A", "B", "C")


def _campaign(seed, specimens_per_site, annotators):
    campaign = generate_campaign(
        seed, SITES, observer_count=8, specimens_per_site=specimens_per_site, annotators_per_specimen=annotators
    )
    annotations = rebuild_annotation_table(build_synthetic_batch(campaign).records)
    truth = {s.specimen_id: s.true_family for s in campaign.specimens}
    return campaign.taxa_families, annotations, truth


def _accuracy(labels, truth):
    return float(np.mean([labels[s] == truth[s] for s in truth]))


def test_unanimous_annotators_give_a_confident_posterior_and_high_accuracy_estimates():
    annotations = [(f"s{i}", f"o{j}", "A") for i in range(6) for j in range(3)]
    result = run_one_coin(annotations, CLASSES)
    assert all(result.inferred_labels[f"s{i}"] == "A" for i in range(6))
    assert all(result.posteriors[f"s{i}"]["A"] > 0.9 for i in range(6))
    assert all(matrix[0][0] > 0.8 for matrix in result.confusion_matrices.values())


def test_implied_confusion_matrices_are_stochastic_with_a_constant_diagonal():
    _, annotations, _ = _campaign(7, 15, 3)
    result = run_one_coin(annotations, ("Baetidae", "Heptageniidae", "Hydropsychidae", "Perlidae"))
    for matrix in result.confusion_matrices.values():
        for r, row in enumerate(matrix):
            assert sum(row) == pytest.approx(1.0)
            assert row[r] == pytest.approx(matrix[0][0])
            assert len({round(v, 12) for i, v in enumerate(row) if i != r}) == 1


@pytest.mark.parametrize(
    ("annotations", "classes", "kwargs", "match"),
    [
        ([], CLASSES, {}, "cannot be empty"),
        ([("s", "o", "A")], ("A",), {}, "at least two"),
        ([("s", "o", "A")], ("A", "A"), {}, "at least two"),
        ([("s", "o", "Z")], CLASSES, {}, "Unknown label"),
        ([("s", "o", "A")], CLASSES, {"smoothing": -1.0}, "non-negative"),
    ],
)
def test_input_validation(annotations, classes, kwargs, match):
    with pytest.raises(ValueError, match=match):
        run_one_coin(annotations, classes, **kwargs)


@given(
    st.lists(
        st.tuples(st.integers(0, 7), st.integers(0, 3), st.sampled_from(CLASSES)),
        min_size=1,
        max_size=60,
        unique_by=lambda t: (t[0], t[1]),
    )
)
@settings(max_examples=100, deadline=None)
def test_posteriors_are_distributions_and_the_map_objective_never_decreases(rows):
    annotations = [(f"s{s}", f"o{o}", label) for s, o, label in rows]
    result = run_one_coin(annotations, CLASSES)
    for posterior in result.posteriors.values():
        assert sum(posterior.values()) == pytest.approx(1.0) and all(0.0 <= p <= 1.0 for p in posterior.values())
    trace = result.map_objective_trace
    assert all(later >= earlier - 1e-7 for earlier, later in zip(trace, trace[1:]))
    for specimen, label in result.inferred_labels.items():
        assert result.posteriors[specimen][label] == max(result.posteriors[specimen].values())


def test_full_model_overfits_in_the_poor_regime_and_one_coin_does_not():
    ds_acc, oc_acc, mv_acc = [], [], []
    for seed in range(300, 316):
        families, annotations, truth = _campaign(seed, 15, 3)
        ds_acc.append(_accuracy(run_dawid_skene(annotations, families).inferred_labels, truth))
        oc_acc.append(_accuracy(run_one_coin(annotations, families).inferred_labels, truth))
        mv_acc.append(_accuracy(majority_vote(annotations, families), truth))
    assert np.mean(oc_acc) - np.mean(ds_acc) > 0.08, "one-coin must clearly beat full Dawid-Skene here"
    assert np.mean(oc_acc) >= np.mean(mv_acc) - 0.03, "and must not be meaningfully worse than majority vote"


def test_one_coin_is_better_calibrated_than_full_dawid_skene_when_data_are_sparse():
    ece_ds, ece_oc = [], []
    for seed in range(400, 410):
        families, annotations, truth = _campaign(seed, 15, 3)
        ids = list(truth)
        labels = [truth[s] for s in ids]
        ece_ds.append(compute_ece([run_dawid_skene(annotations, families).posteriors[s] for s in ids], labels))
        ece_oc.append(compute_ece([run_one_coin(annotations, families).posteriors[s] for s in ids], labels))
    assert np.mean(ece_oc) < np.mean(ece_ds) - 0.05


def test_with_abundant_data_full_dawid_skene_is_still_at_least_as_good():
    ds_acc, oc_acc = [], []
    for seed in range(300, 308):
        families, annotations, truth = _campaign(seed, 70, 5)
        ds_acc.append(_accuracy(run_dawid_skene(annotations, families).inferred_labels, truth))
        oc_acc.append(_accuracy(run_one_coin(annotations, families).inferred_labels, truth))
    assert np.mean(ds_acc) >= np.mean(oc_acc) - 0.005


def test_posterior_provider_follows_the_data_volume():
    families, sparse, _ = _campaign(11, 15, 3)
    _, rich, _ = _campaign(11, 70, 5)
    assert compute_posterior_probabilities(sparse, families)[1] == "one-coin"
    assert compute_posterior_probabilities(rich, families)[1] == "dawid-skene"
