"""One-coin Dawid-Skene: one accuracy per annotator, for the sparse-annotation regime.

Full Dawid-Skene estimates a K x K confusion matrix per annotator (K*(K-1) free parameters each),
which overfits when each annotator labels few specimens. The one-coin model keeps a single accuracy
``a_j`` per annotator: P(label = l | true = k) is ``a_j`` if ``l == k`` and ``(1 - a_j) / (K - 1)``
otherwise. It cannot represent systematic confusions between specific classes (see
docs/math_registry.md for the measured trade-off).
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

from oah.reliability.dawid_skene import DawidSkeneResult

_EPS = 1e-12


def run_one_coin(
    annotations: Sequence[tuple[str, str, str]],
    classes: Sequence[str],
    smoothing: float = 1.0,
    max_iter: int = 200,
    tol: float = 1e-8,
) -> DawidSkeneResult:
    """Fit the one-coin model by EM with MAP priors and return a Dawid-Skene-compatible result.

    Priors: Dirichlet(smoothing + 1) on class frequencies (same as ``run_dawid_skene``) and Beta(2, 2)
    on every annotator accuracy, so ``a_j = (correct_j + 1) / (n_j + 2)`` in the M-step, where
    ``correct_j`` is the expected number of correct labels of annotator j. The MAP objective never
    decreases across iterations. ``confusion_matrices`` holds the implied per-annotator matrices.
    """
    if not annotations:
        raise ValueError("Annotation table cannot be empty.")
    class_list = tuple(classes)
    if len(class_list) < 2 or len(set(class_list)) != len(class_list):
        raise ValueError("classes must contain at least two distinct class labels.")
    if smoothing < 0:
        raise ValueError("smoothing must be non-negative.")
    k_count = len(class_list)
    class_index = {c: i for i, c in enumerate(class_list)}
    for _s, _o, label in annotations:
        if label not in class_index:
            raise ValueError(f"Unknown label '{label}' not in classes.")

    specimens = list(dict.fromkeys(a[0] for a in annotations))
    observers = list(dict.fromkeys(a[1] for a in annotations))
    spec_index = {s: i for i, s in enumerate(specimens)}
    obs_index = {o: i for i, o in enumerate(observers)}
    s_idx = np.array([spec_index[a[0]] for a in annotations])
    o_idx = np.array([obs_index[a[1]] for a in annotations])
    l_idx = np.array([class_index[a[2]] for a in annotations])
    m_count, j_count, a_count = len(specimens), len(observers), len(annotations)
    per_observer = np.bincount(o_idx, minlength=j_count).astype(float)

    posterior = np.zeros((m_count, k_count))
    np.add.at(posterior, (s_idx, l_idx), 1.0)
    posterior /= posterior.sum(axis=1, keepdims=True)

    ll_trace: list[float] = []
    map_trace: list[float] = []
    priors = np.full(k_count, 1.0 / k_count)
    accuracy = np.full(j_count, 0.5)
    rows_all = np.arange(a_count)
    for _ in range(max_iter):
        priors = (posterior.sum(axis=0) + smoothing) / (m_count + k_count * smoothing)
        correct = np.bincount(o_idx, weights=posterior[s_idx, l_idx], minlength=j_count)
        accuracy = np.clip((correct + 1.0) / (per_observer + 2.0), _EPS, 1.0 - _EPS)

        log_w = np.tile(np.log(np.maximum(priors, _EPS)), (m_count, 1))
        wrong = np.log((1.0 - accuracy[o_idx]) / (k_count - 1))
        rows = np.repeat(wrong[:, None], k_count, axis=1)
        rows[rows_all, l_idx] = np.log(accuracy[o_idx])
        np.add.at(log_w, s_idx, rows)

        peak = log_w.max(axis=1, keepdims=True)
        log_lik = float((peak + np.log(np.exp(log_w - peak).sum(axis=1, keepdims=True))).sum())
        log_prior = smoothing * float(np.log(np.maximum(priors, _EPS)).sum()) + float(
            (np.log(accuracy) + np.log(1.0 - accuracy)).sum()
        )
        ll_trace.append(log_lik)
        map_trace.append(log_lik + log_prior)

        posterior = np.exp(log_w - peak)
        posterior /= posterior.sum(axis=1, keepdims=True)
        if len(map_trace) > 1 and (map_trace[-1] - map_trace[-2]) < tol:
            break

    off_diagonal = (1.0 - accuracy) / (k_count - 1)
    confusion = {
        observers[j]: [
            [float(accuracy[j]) if r == c else float(off_diagonal[j]) for c in range(k_count)] for r in range(k_count)
        ]
        for j in range(j_count)
    }
    return DawidSkeneResult(
        class_priors={c: float(priors[i]) for i, c in enumerate(class_list)},
        confusion_matrices=confusion,
        posteriors={s: {c: float(posterior[spec_index[s], i]) for i, c in enumerate(class_list)} for s in specimens},
        inferred_labels={
            s: class_list[max(range(k_count), key=lambda k: (posterior[spec_index[s], k], -k))] for s in specimens
        },
        log_likelihood_trace=tuple(ll_trace),
        map_objective_trace=tuple(map_trace),
        iterations=len(ll_trace),
    )
