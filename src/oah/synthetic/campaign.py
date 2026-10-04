"""Seeded, ground-truth citizen-science macroinvertebrate campaign simulator."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Sequence

import numpy as np

GENERATOR_VERSION = "1.0"
DEFAULT_TAXA_FAMILIES = ("Baetidae", "Heptageniidae", "Hydropsychidae", "Perlidae")


@dataclass(frozen=True)
class Observer:
    """A simulated observer and its taxon-family confusion matrix."""

    identifier: str
    skill: float
    confusion_matrix: tuple[tuple[float, ...], ...]
    role: str = "standard"


@dataclass(frozen=True)
class Specimen:
    """A sampled specimen with a true family ground truth."""

    specimen_id: str
    site_id: str
    true_family: str


@dataclass(frozen=True)
class CampaignObservation:
    """One synthetic citizen-science identification observation."""

    specimen_id: str
    site_id: str
    observer_id: str
    reported_family: str
    timestamp: datetime


@dataclass(frozen=True)
class Campaign:
    """All simulator outputs for one deterministically seeded campaign."""

    seed: int
    generator_version: str
    taxa_families: tuple[str, ...]
    observers: tuple[Observer, ...]
    specimens: tuple[Specimen, ...]
    observations: tuple[CampaignObservation, ...]


def _confusion_matrix(skill: float, family_count: int) -> tuple[tuple[float, ...], ...]:
    off_diagonal = (1.0 - skill) / (family_count - 1)
    return tuple(
        tuple(skill if row == column else off_diagonal for column in range(family_count))
        for row in range(family_count)
    )


def _adversarial_confusion_matrix(skill: float, family_count: int) -> tuple[tuple[float, ...], ...]:
    off_diagonal = (1.0 - skill) / (family_count - 1)
    rows = []
    for row in range(family_count):
        row_vals = []
        for col in range(family_count):
            if row == 0:
                val = skill if col == 1 else off_diagonal
            elif row == 1:
                val = skill if col == 0 else off_diagonal
            else:
                val = skill if col == row else off_diagonal
            row_vals.append(val)
        rows.append(tuple(row_vals))
    return tuple(rows)


def generate_campaign(
    seed: int,
    site_ids: Sequence[str],
    observer_count: int = 10,
    specimens_per_site: int = 5,
    annotators_per_specimen: int = 3,
    taxa_families: Sequence[str] = DEFAULT_TAXA_FAMILIES,
) -> Campaign:
    """Generate a campaign from location labels without accessing location data."""
    if not site_ids or any(not site_id for site_id in site_ids):
        raise ValueError("site_ids must contain existing Location identifiers used only as labels.")
    if specimens_per_site < 1:
        raise ValueError("specimens_per_site must be positive.")
    if annotators_per_specimen < 2:
        raise ValueError("annotators_per_specimen must be at least 2.")
    if observer_count < annotators_per_specimen:
        raise ValueError("observer_count must be at least annotators_per_specimen.")
    families = tuple(taxa_families)
    if len(families) < 2 or len(set(families)) != len(families):
        raise ValueError("taxa_families must contain at least two distinct families.")

    generator = np.random.default_rng(seed)

    num_weak = max(1, observer_count // 4)
    has_adversarial = observer_count >= 4

    observers_list = []
    for i in range(observer_count):
        identifier = f"observer-{i + 1}"
        if i < num_weak:
            role = "weak"
            skill = float(generator.uniform(0.30, 0.55))
            cm = _confusion_matrix(skill, len(families))
        elif has_adversarial and i == num_weak:
            role = "adversarial"
            skill = float(generator.uniform(0.70, 0.90))
            cm = _adversarial_confusion_matrix(skill, len(families))
        else:
            role = "standard"
            skill = float(generator.uniform(0.55, 0.95))
            cm = _confusion_matrix(skill, len(families))
        observers_list.append(Observer(identifier, skill, cm, role))

    observers = tuple(observers_list)

    start = datetime(2026, 1, 1, tzinfo=UTC)
    specimens = []
    observations = []

    for site_index, site_id in enumerate(site_ids):
        for spec_idx in range(specimens_per_site):
            specimen_id = f"specimen-{site_id}-{spec_idx + 1}"
            true_idx = int(generator.integers(0, len(families)))
            true_family = families[true_idx]
            specimens.append(Specimen(specimen_id, site_id, true_family))

            annotator_indices = generator.choice(observer_count, size=annotators_per_specimen, replace=False)
            for ann_idx, obs_idx in enumerate(annotator_indices):
                obs = observers[int(obs_idx)]
                reported_idx = int(
                    generator.choice(len(families), p=obs.confusion_matrix[true_idx])
                )
                ts = start + timedelta(days=site_index, hours=spec_idx, minutes=ann_idx * 10)
                observations.append(
                    CampaignObservation(
                        specimen_id=specimen_id,
                        site_id=site_id,
                        observer_id=obs.identifier,
                        reported_family=families[reported_idx],
                        timestamp=ts,
                    )
                )

    return Campaign(
        seed=seed,
        generator_version=GENERATOR_VERSION,
        taxa_families=families,
        observers=observers,
        specimens=tuple(specimens),
        observations=tuple(observations),
    )
