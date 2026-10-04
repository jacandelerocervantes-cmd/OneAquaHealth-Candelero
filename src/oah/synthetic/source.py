"""Shared-source adapter for synthetic FHIR Observation records."""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from oah.ingest.sources import SourceRecord
from oah.synthetic.fhir import SyntheticBatch


@dataclass(frozen=True)
class SyntheticObservationSource:
    """Expose a synthetic batch through the ObservationSource protocol."""

    batch: SyntheticBatch

    def observations(self) -> Iterator[SourceRecord]:
        yield from self.batch.records
