"""Split conformal prediction for classification."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, NamedTuple, Sequence

import numpy as np

from oah.reliability import recommend_method, run_dawid_skene, run_one_coin


@dataclass(frozen=True)
class ConformalPredictionSet:
    """Result of conformal prediction set construction for one specimen."""

    specimen_id: str
    prediction_set: tuple[str, ...]
    probabilities: dict[str, float]
    quantile_cutoff: float
    probability_provider: str
    tag: str = "synthetic"
    # Set only by class-conditional prediction: the per-class cutoffs actually used. In that case
    # ``quantile_cutoff`` is the largest of them and is informational only.
    class_quantiles: dict[str, float] | None = None


class RiskCoveragePoint(NamedTuple):
    """Point on a risk-coverage selective prediction curve."""

    threshold: float
    coverage: float
    risk: float


def assert_disjoint_specimens(
    calibration_true: Mapping[str, str],
    test_true: Mapping[str, str],
) -> None:
    """Assert that calibration and test specimen ID sets are strictly disjoint.

    Raises:
        ValueError: If any specimen ID is present in both calibration and test sets.
    """
    intersection = set(calibration_true.keys()) & set(test_true.keys())
    if intersection:
        sample_overlap = sorted(list(intersection))[:5]
        raise ValueError(
            f"Calibration and test specimen sets are not disjoint. Overlapping IDs ({len(intersection)} total): {sample_overlap}"
        )


def compute_calibration_quantile(
    calibration_scores: Sequence[float],
    alpha: float,
) -> float:
    """Compute finite-sample conformal calibration quantile q.

    Args:
        calibration_scores: 1D sequence of nonconformity scores s_i = 1 - p_i(y_i^true).
        alpha: Misclassification error rate in (0, 1).

    Returns:
        Quantile cutoff q.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1).")
    n = len(calibration_scores)
    min_required = math.ceil(1.0 / alpha)
    if n == 0 or n < min_required:
        raise ValueError(
            f"Calibration set size {n} is smaller than required minimum ceil(1/alpha) = {min_required}."
        )

    scores = np.sort(np.asarray(calibration_scores, dtype=float))
    k = math.ceil((n + 1) * (1.0 - alpha))
    if k > n:
        return 1.0
    return float(scores[k - 1])


def predict_conformal_set(
    probabilities: Mapping[str, float],
    quantile_cutoff: float,
    provider: str,
    specimen_id: str = "",
    tag: str = "synthetic",
) -> ConformalPredictionSet:
    """Construct prediction set C(x) = {y : 1 - p(y) <= q}.

    `provider` is a required argument with no default value to prevent silent mislabeling.
    """
    classes = sorted(probabilities.keys(), key=lambda c: (-probabilities[c], c))
    prediction_set = tuple(c for c in classes if (1.0 - probabilities[c]) <= quantile_cutoff + 1e-12)
    return ConformalPredictionSet(
        specimen_id=specimen_id,
        prediction_set=prediction_set,
        probabilities=dict(probabilities),
        quantile_cutoff=float(quantile_cutoff),
        probability_provider=provider,
        tag=tag,
    )


@dataclass(frozen=True)
class ClassConditionalCalibration:
    """Per-class (Mondrian) conformal cutoffs and how well each class was calibrated."""

    alpha: float
    quantiles: dict[str, float]
    class_counts: dict[str, int]
    uncalibrated_classes: tuple[str, ...]  # classes with too few calibration examples; cutoff forced to 1.0


def calibrate_class_conditional(
    posteriors: Mapping[str, Mapping[str, float]],
    true_labels: Mapping[str, str],
    classes: Sequence[str],
    alpha: float,
    on_insufficient: str = "raise",
) -> ClassConditionalCalibration:
    """Calibrate one conformal cutoff per true class (Mondrian / class-conditional conformal).

    For class ``c`` the calibration scores are ``1 - p(c)`` over calibration specimens whose TRUE
    class is ``c``; the cutoff is their finite-sample quantile at level ``alpha``. Under
    exchangeability within each class this gives ``P(Y in C(X) | Y = c) >= 1 - alpha`` for every
    class, not just on average. ``true_labels`` must be expert-verified labels.

    A class with fewer than ``ceil(1/alpha)`` calibration examples cannot be calibrated.
    ``on_insufficient="raise"`` (default) rejects it; ``"include"`` sets its cutoff to 1.0, which keeps
    the guarantee but puts that class into EVERY prediction set, so almost nothing is a singleton.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1).")
    if on_insufficient not in ("raise", "include"):
        raise ValueError("on_insufficient must be 'raise' or 'include'.")
    class_list = tuple(classes)
    if len(set(class_list)) != len(class_list) or len(class_list) < 2:
        raise ValueError("classes must contain at least two distinct labels.")
    scores: dict[str, list[float]] = {c: [] for c in class_list}
    for specimen_id, true_class in true_labels.items():
        if true_class not in scores:
            raise ValueError(f"True label {true_class!r} of specimen {specimen_id!r} is not in classes.")
        if specimen_id not in posteriors or true_class not in posteriors[specimen_id]:
            raise ValueError(f"No posterior for the true class of specimen {specimen_id!r}.")
        scores[true_class].append(1.0 - float(posteriors[specimen_id][true_class]))

    minimum = math.ceil(1.0 / alpha)
    short = tuple(c for c in class_list if len(scores[c]) < minimum)
    if short and on_insufficient == "raise":
        counts = {c: len(scores[c]) for c in short}
        raise ValueError(f"Classes with fewer than ceil(1/alpha) = {minimum} calibration examples: {counts}.")
    quantiles = {c: 1.0 if c in short else compute_calibration_quantile(scores[c], alpha) for c in class_list}
    return ClassConditionalCalibration(alpha, quantiles, {c: len(scores[c]) for c in class_list}, short)


def predict_class_conditional_set(
    probabilities: Mapping[str, float],
    calibration: ClassConditionalCalibration,
    provider: str,
    specimen_id: str = "",
    tag: str = "synthetic",
) -> ConformalPredictionSet:
    """Construct C(x) = {y : 1 - p(y) <= q_y} with the per-class cutoffs of ``calibration``."""
    unknown = set(probabilities) - set(calibration.quantiles)
    if unknown:
        raise ValueError(f"Classes without a calibrated cutoff: {sorted(unknown)}.")
    ordered = sorted(probabilities, key=lambda c: (-probabilities[c], c))
    chosen = tuple(c for c in ordered if (1.0 - probabilities[c]) <= calibration.quantiles[c] + 1e-12)
    return ConformalPredictionSet(
        specimen_id=specimen_id,
        prediction_set=chosen,
        probabilities=dict(probabilities),
        quantile_cutoff=float(max(calibration.quantiles[c] for c in probabilities)),
        probability_provider=provider,
        tag=tag,
        class_quantiles={c: float(calibration.quantiles[c]) for c in probabilities},
    )


def coverage_by_class(
    prediction_sets: Sequence[Sequence[str]],
    true_labels: Sequence[str],
) -> dict[str, tuple[float, int]]:
    """Empirical coverage per TRUE class as ``{class: (coverage, n)}``."""
    if len(prediction_sets) != len(true_labels):
        raise ValueError("prediction_sets and true_labels must have the same length.")
    hits: dict[str, list[bool]] = {}
    for chosen, truth in zip(prediction_sets, true_labels):
        hits.setdefault(truth, []).append(truth in chosen)
    return {c: (float(np.mean(v)), len(v)) for c, v in sorted(hits.items())}


def set_size_summary(prediction_sets: Sequence[Sequence[str]]) -> dict[str, float]:
    """Share of empty, singleton and ambiguous sets, plus the mean size (queue workload)."""
    if not prediction_sets:
        return {"empty_rate": 0.0, "singleton_rate": 0.0, "ambiguous_rate": 0.0, "mean_size": 0.0}
    sizes = np.array([len(s) for s in prediction_sets])
    return {
        "empty_rate": float(np.mean(sizes == 0)),
        "singleton_rate": float(np.mean(sizes == 1)),
        "ambiguous_rate": float(np.mean(sizes >= 2)),
        "mean_size": float(sizes.mean()),
    }


def compute_posterior_probabilities(
    annotations: Sequence[tuple[str, str, str]],
    classes: Sequence[str],
    smoothing: float = 1.0,
) -> tuple[dict[str, dict[str, float]], str]:
    """Posterior class probabilities per specimen from the aggregation method suited to the data volume.

    Dawid-Skene when there are enough annotations per observer, otherwise the one-coin model (see
    ``recommend_method``). Returns ``(posteriors, provider)`` with provider ``"dawid-skene"`` or
    ``"one-coin"``.
    """
    recommended, _diag = recommend_method(annotations, threshold=50.0)
    class_list = tuple(classes)
    if recommended == "dawid-skene":
        return run_dawid_skene(annotations, class_list, smoothing=smoothing).posteriors, "dawid-skene"
    return run_one_coin(annotations, class_list, smoothing=smoothing).posteriors, "one-coin"


def compute_risk_coverage_curve(
    posteriors: Sequence[dict[str, float]],
    true_labels: Sequence[str],
    thresholds: Sequence[float] | None = None,
) -> list[RiskCoveragePoint]:
    """Compute risk-coverage selective prediction curve across confidence thresholds.

    Args:
        posteriors: List of predicted class posterior probability dicts.
        true_labels: List of ground-truth class labels.
        thresholds: Fixed sequence of confidence thresholds in [0, 1]. Defaults to 0.0..1.0 by 0.05 steps.

    Returns:
        List of RiskCoveragePoint(threshold, coverage, risk).
    """
    if len(posteriors) != len(true_labels):
        raise ValueError("posteriors and true_labels must have the same length.")

    if thresholds is None:
        grid = np.linspace(0.0, 1.0, 21)
    else:
        grid = np.asarray(thresholds, dtype=float)

    n_total = len(posteriors)
    if n_total == 0:
        return [RiskCoveragePoint(float(t), 0.0, 0.0) for t in grid]

    confidences = []
    is_correct = []
    for post, true_c in zip(posteriors, true_labels):
        pred_c = max(post.keys(), key=lambda c: (post[c], c))
        conf = float(post[pred_c])
        correct = 1.0 if pred_c == true_c else 0.0
        confidences.append(conf)
        is_correct.append(correct)

    conf_arr = np.asarray(confidences, dtype=float)
    corr_arr = np.asarray(is_correct, dtype=float)

    curve = []
    for t in grid:
        t_val = float(t)
        kept_mask = conf_arr >= (t_val - 1e-12)
        n_kept = int(np.sum(kept_mask))
        coverage = float(n_kept / n_total)
        if n_kept > 0:
            risk = float(1.0 - np.mean(corr_arr[kept_mask]))
        else:
            risk = 0.0
        curve.append(RiskCoveragePoint(t_val, coverage, risk))

    return curve


def compute_ece(
    posteriors: Sequence[dict[str, float]],
    true_labels: Sequence[str],
    num_bins: int = 10,
) -> float:
    """Compute Expected Calibration Error (ECE) across confidence bins."""
    confidences = []
    accuracies = []
    for post, true_c in zip(posteriors, true_labels):
        pred_c = max(post.keys(), key=lambda c: (post[c], c))
        conf = post[pred_c]
        acc = 1.0 if pred_c == true_c else 0.0
        confidences.append(conf)
        accuracies.append(acc)

    conf_arr = np.asarray(confidences)
    acc_arr = np.asarray(accuracies)

    bin_boundaries = np.linspace(0.0, 1.0, num_bins + 1)
    ece = 0.0
    total = len(conf_arr)

    for i in range(num_bins):
        bin_lower = bin_boundaries[i]
        bin_upper = bin_boundaries[i + 1]
        if i == 0:
            in_bin = (conf_arr >= bin_lower) & (conf_arr <= bin_upper)
        else:
            in_bin = (conf_arr > bin_lower) & (conf_arr <= bin_upper)
        bin_size = np.sum(in_bin)
        if bin_size > 0:
            avg_conf = float(np.mean(conf_arr[in_bin]))
            avg_acc = float(np.mean(acc_arr[in_bin]))
            ece += (bin_size / total) * abs(avg_conf - avg_acc)

    return float(ece)
