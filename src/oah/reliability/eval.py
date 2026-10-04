"""Evaluation metrics comparing Dawid-Skene and majority vote against campaign ground truth."""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np

from oah.reliability.dawid_skene import DawidSkeneResult
from oah.synthetic.campaign import Campaign


def compute_macro_f1(
    true_labels: Mapping[str, str],
    pred_labels: Mapping[str, str],
    classes: Sequence[str],
) -> float:
    """Compute macro-averaged F1 score across all classes."""
    f1_scores = []
    for c in classes:
        tp = sum(1 for item_id, true_c in true_labels.items() if true_c == c and pred_labels.get(item_id) == c)
        fp = sum(1 for item_id, true_c in true_labels.items() if true_c != c and pred_labels.get(item_id) == c)
        fn = sum(1 for item_id, true_c in true_labels.items() if true_c == c and pred_labels.get(item_id) != c)
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0
        f1_scores.append(f1)
    return float(np.mean(f1_scores))


def _scalar(metrics: Mapping[str, float | dict[str, float]], key: str) -> float:
    """A metric that must be a single number (some entries of the metrics dict are nested)."""
    value = metrics[key]
    if isinstance(value, dict):
        raise TypeError(f"metric {key!r} is a mapping, not a scalar")
    return float(value)


def evaluate_reliability(
    campaign: Campaign,
    result: DawidSkeneResult,
    mv_labels: Mapping[str, str],
) -> dict[str, float | dict[str, float]]:
    """Evaluate majority vote and Dawid-Skene against simulator ground truth."""
    true_labels = {spec.specimen_id: spec.true_family for spec in campaign.specimens}
    spec_count = len(campaign.specimens)

    mv_correct = sum(1 for spec_id, true_c in true_labels.items() if mv_labels.get(spec_id) == true_c)
    ds_correct = sum(
        1 for spec_id, true_c in true_labels.items() if result.inferred_labels.get(spec_id) == true_c
    )

    mv_accuracy = mv_correct / spec_count if spec_count > 0 else 0.0
    ds_accuracy = ds_correct / spec_count if spec_count > 0 else 0.0

    mv_macro_f1 = compute_macro_f1(true_labels, mv_labels, campaign.taxa_families)
    ds_macro_f1 = compute_macro_f1(true_labels, result.inferred_labels, campaign.taxa_families)

    log_losses = []
    for spec in campaign.specimens:
        true_c = spec.true_family
        post = result.posteriors.get(spec.specimen_id, {}).get(true_c, 1e-12)
        post = max(post, 1e-12)
        log_losses.append(-math.log(post))
    mean_log_loss = float(np.mean(log_losses)) if log_losses else 0.0

    frob_distances = {}
    for obs in campaign.observers:
        true_cm = np.array(obs.confusion_matrix, dtype=float)
        est_cm = np.array(result.confusion_matrices.get(obs.identifier, []), dtype=float)
        if est_cm.shape == true_cm.shape:
            dist = float(np.linalg.norm(est_cm - true_cm, ord="fro"))
        else:
            dist = float("nan")
        frob_distances[obs.identifier] = dist

    mean_frob = float(np.mean(list(frob_distances.values()))) if frob_distances else 0.0

    return {
        "mv_accuracy": mv_accuracy,
        "ds_accuracy": ds_accuracy,
        "mv_macro_f1": mv_macro_f1,
        "ds_macro_f1": ds_macro_f1,
        "log_loss": mean_log_loss,
        "mean_frobenius_distance": mean_frob,
        "frobenius_distances": frob_distances,
    }


def run_regime_experiment(
    seeds: Sequence[int],
    site_ids: Sequence[str],
    observer_count: int,
    specimens_per_site: int,
    annotators_per_specimen: int,
    smoothing: float = 1.0,
) -> dict:
    """Run reliability evaluation over a regime across multiple seeds.

    Raises:
        ValueError: If ``seeds`` is empty (there is nothing to average; NaN summaries would hide that).
    """
    if not seeds:
        raise ValueError("seeds must not be empty.")
    from oah.reliability.dawid_skene import majority_vote, run_dawid_skene
    from oah.synthetic.campaign import generate_campaign
    from oah.synthetic.fhir import build_synthetic_batch, rebuild_annotation_table

    eval_results = []
    ds_win_count = 0
    for seed in seeds:
        campaign = generate_campaign(
            seed=seed,
            site_ids=site_ids,
            observer_count=observer_count,
            specimens_per_site=specimens_per_site,
            annotators_per_specimen=annotators_per_specimen,
        )
        batch = build_synthetic_batch(campaign)
        annotations = rebuild_annotation_table(batch.records)
        mv_labels = majority_vote(annotations, campaign.taxa_families)
        ds_result = run_dawid_skene(annotations, campaign.taxa_families, smoothing=smoothing)
        metrics = evaluate_reliability(campaign, ds_result, mv_labels)
        eval_results.append(metrics)
        if _scalar(metrics, "ds_accuracy") > _scalar(metrics, "mv_accuracy"):
            ds_win_count += 1

    keys = ("mv_accuracy", "ds_accuracy", "mv_macro_f1", "ds_macro_f1", "log_loss", "mean_frobenius_distance")
    summary: dict[str, Any] = {}
    for k in keys:
        vals = [_scalar(r, k) for r in eval_results]
        summary[k] = {"mean": float(np.mean(vals)), "std": float(np.std(vals))}
    summary["ds_win_fraction"] = float(ds_win_count / len(seeds))
    return summary
