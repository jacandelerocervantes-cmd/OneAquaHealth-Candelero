"""Dawid-Skene observer reliability estimation via Expectation-Maximization (EM)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class DawidSkeneResult:
    """Outputs from Dawid-Skene EM estimation."""

    class_priors: dict[str, float]
    confusion_matrices: dict[str, list[list[float]]]
    posteriors: dict[str, dict[str, float]]
    inferred_labels: dict[str, str]
    log_likelihood_trace: tuple[float, ...]
    map_objective_trace: tuple[float, ...]
    iterations: int


def majority_vote(
    annotations: Sequence[tuple[str, str, str]],
    classes: Sequence[str],
) -> dict[str, str]:
    """Compute baseline majority vote with deterministic tie-breaking.

    Args:
        annotations: Sequence of (specimen_id, observer_id, label) tuples.
        classes: Allowed class labels in fixed canonical order.

    Returns:
        Mapping from specimen_id to winning class label.
    """
    if not annotations:
        raise ValueError("Annotation table cannot be empty.")
    class_set = set(classes)
    if len(classes) < 2 or len(class_set) != len(classes):
        raise ValueError("classes must contain at least two distinct class labels.")

    spec_votes: dict[str, dict[str, int]] = {}
    for spec_id, _obs_id, label in annotations:
        if label not in class_set:
            raise ValueError(f"Unknown label '{label}' not in classes.")
        if spec_id not in spec_votes:
            spec_votes[spec_id] = {c: 0 for c in classes}
        spec_votes[spec_id][label] += 1

    inferred = {}
    for spec_id, votes in spec_votes.items():
        best_label = max(classes, key=lambda c: (votes[c], -classes.index(c)))
        inferred[spec_id] = best_label
    return inferred


def run_dawid_skene(
    annotations: Sequence[tuple[str, str, str]],
    classes: Sequence[str],
    smoothing: float = 1.0,
    max_iter: int = 100,
    tol: float = 1e-5,
) -> DawidSkeneResult:
    """Fit Dawid-Skene EM model with Laplace smoothing.

    Args:
        annotations: Sequence of (specimen_id, observer_id, label) tuples.
        classes: Allowed class labels in fixed canonical order.
        smoothing: Additive Laplace smoothing parameter alpha >= 0.
        max_iter: Maximum number of EM iterations.
        tol: Convergence threshold for MAP objective increase.

    Returns:
        DawidSkeneResult instance.
    """
    if not annotations:
        raise ValueError("Annotation table cannot be empty.")
    class_list = tuple(classes)
    class_set = set(class_list)
    if len(class_list) < 2 or len(class_set) != len(class_list):
        raise ValueError("classes must contain at least two distinct class labels.")
    if smoothing < 0:
        raise ValueError("smoothing must be non-negative.")

    K = len(class_list)
    class_to_idx = {c: idx for idx, c in enumerate(class_list)}

    specimens = list(dict.fromkeys(a[0] for a in annotations))
    observers = list(dict.fromkeys(a[1] for a in annotations))

    M = len(specimens)
    J = len(observers)
    spec_to_idx = {s: idx for idx, s in enumerate(specimens)}
    obs_to_idx = {o: idx for idx, o in enumerate(observers)}

    obs_by_specimen: list[list[tuple[int, int]]] = [[] for _ in range(M)]
    obs_by_observer: list[list[tuple[int, int]]] = [[] for _ in range(J)]

    spec_vote_counts = np.zeros((M, K), dtype=float)

    for spec_id, obs_id, label in annotations:
        if label not in class_to_idx:
            raise ValueError(f"Unknown label '{label}' not in classes.")
        i = spec_to_idx[spec_id]
        j = obs_to_idx[obs_id]
        k = class_to_idx[label]
        obs_by_specimen[i].append((j, k))
        obs_by_observer[j].append((i, k))
        spec_vote_counts[i, k] += 1.0

    T = np.zeros((M, K), dtype=float)
    for i in range(M):
        total_votes = spec_vote_counts[i].sum()
        if total_votes > 0:
            T[i] = spec_vote_counts[i] / total_votes
        else:
            T[i] = 1.0 / K

    priors = np.zeros(K, dtype=float)
    confusion_matrices = np.zeros((J, K, K), dtype=float)
    log_likelihood_trace: list[float] = []
    map_objective_trace: list[float] = []

    for it in range(max_iter):
        priors = (T.sum(axis=0) + smoothing) / (M + K * smoothing)

        for j in range(J):
            counts = np.zeros((K, K), dtype=float)
            for i, k_obs in obs_by_observer[j]:
                counts[:, k_obs] += T[i, :]
            row_sums = T[[i for i, _ in obs_by_observer[j]], :].sum(axis=0) if obs_by_observer[j] else np.zeros(K)
            for k in range(K):
                denom = row_sums[k] + K * smoothing
                if denom > 0:
                    confusion_matrices[j, k, :] = (counts[k, :] + smoothing) / denom
                else:
                    confusion_matrices[j, k, :] = 1.0 / K

        log_w = np.zeros((M, K), dtype=float)
        for i in range(M):
            for k in range(K):
                val = np.log(priors[k])
                for j, k_obs in obs_by_specimen[i]:
                    val += np.log(max(confusion_matrices[j, k, k_obs], 1e-12))
                log_w[i, k] = val

        max_log_w = log_w.max(axis=1, keepdims=True)
        log_sum_exp = max_log_w + np.log(np.exp(log_w - max_log_w).sum(axis=1, keepdims=True))
        log_likelihood = float(log_sum_exp.sum())

        log_prior_priors = smoothing * np.sum(np.log(np.maximum(priors, 1e-12)))
        log_prior_cms = smoothing * np.sum(np.log(np.maximum(confusion_matrices, 1e-12)))
        map_objective = log_likelihood + float(log_prior_priors + log_prior_cms)

        log_likelihood_trace.append(log_likelihood)
        map_objective_trace.append(map_objective)

        T = np.exp(log_w - max_log_w)
        T /= T.sum(axis=1, keepdims=True)

        if it > 0 and (map_objective_trace[-1] - map_objective_trace[-2]) < tol:
            break

    priors_dict = {c: float(priors[k]) for k, c in enumerate(class_list)}
    cms_dict = {
        obs_id: confusion_matrices[obs_to_idx[obs_id]].tolist()
        for obs_id in observers
    }
    posteriors_dict = {
        spec_id: {c: float(T[spec_to_idx[spec_id], k]) for k, c in enumerate(class_list)}
        for spec_id in specimens
    }

    inferred_labels_dict = {}
    for spec_id in specimens:
        i = spec_to_idx[spec_id]
        best_k = max(range(K), key=lambda k: (T[i, k], -k))
        inferred_labels_dict[spec_id] = class_list[best_k]

    return DawidSkeneResult(
        class_priors=priors_dict,
        confusion_matrices=cms_dict,
        posteriors=posteriors_dict,
        inferred_labels=inferred_labels_dict,
        log_likelihood_trace=tuple(log_likelihood_trace),
        map_objective_trace=tuple(map_objective_trace),
        iterations=len(log_likelihood_trace),
    )


def recommend_method(
    annotations: Sequence[tuple[str, str, str]],
    threshold: float = 50.0,
) -> tuple[str, dict[str, float | int]]:
    """Recommend the aggregation method from the mean number of annotations per observer.

    At or above ``threshold`` the full Dawid-Skene model has enough data per observer; below it the
    one-coin model (``oah.reliability.one_coin``) is recommended because it estimates one accuracy per
    observer instead of a full confusion matrix. Measured trade-offs are in docs/math_registry.md.

    Args:
        annotations: Sequence of (specimen_id, observer_id, label) tuples.
        threshold: Minimum mean annotations per observer required for Dawid-Skene.

    Returns:
        Tuple of (recommended_method_name, diagnostics_dict).
        recommended_method_name is either 'one-coin' (sparse regime) or 'dawid-skene'.
    """
    if not annotations:
        raise ValueError("Annotation table cannot be empty.")
    observers = {a[1] for a in annotations}
    num_observers = len(observers)
    total_annotations = len(annotations)
    mean_ann_per_obs = total_annotations / num_observers if num_observers > 0 else 0.0

    recommended = "dawid-skene" if mean_ann_per_obs >= threshold else "one-coin"
    diagnostics = {
        "total_annotations": total_annotations,
        "num_observers": num_observers,
        "mean_annotations_per_observer": float(mean_ann_per_obs),
        "threshold": float(threshold),
    }
    return recommended, diagnostics
