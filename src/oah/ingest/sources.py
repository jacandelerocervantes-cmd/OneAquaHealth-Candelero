"""Origin-preserving Observation source interfaces and mixing guard."""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Literal, Protocol

from oah.ingest.sandbox_client import SandboxClient

Origin = Literal["real-sandbox", "synthetic"]


@dataclass(frozen=True)
class SourceRecord:
    """A FHIR resource paired with its immutable data origin."""

    resource: dict
    origin: Origin


class ObservationSource(Protocol):
    """A source that yields origin-labeled FHIR Observation records."""

    def observations(self) -> Iterator[SourceRecord]:
        """Yield records without dropping their origin."""


def origin_from_resource(resource: dict, default_origin: Origin | None = None) -> Origin:
    """Read a resource's origin, failing closed when it cannot be established.

    A ``synthetic`` tag always wins. An untagged resource is labelled only with the origin its caller
    declares in ``default_origin`` (the sandbox client declares ``real-sandbox``); with no declaration
    it is rejected, so a synthetic resource that lost its tag can never be presented as real.
    """
    tags = resource.get("meta", {}).get("tag", [])
    if any(tag.get("code") == "synthetic" for tag in tags):
        return "synthetic"
    if default_origin is None:
        raise ValueError(
            "Untagged resource: declare its origin with default_origin or wrap it in a SourceRecord."
        )
    return default_origin


def source_records(
    records: Iterable[dict | SourceRecord], default_origin: Origin | None = None
) -> list[SourceRecord]:
    """Normalize resource dictionaries to origin-preserving records (see ``origin_from_resource``)."""
    return [
        record
        if isinstance(record, SourceRecord)
        else SourceRecord(record, origin_from_resource(record, default_origin))
        for record in records
    ]


def assert_single_origin(records: Iterable[SourceRecord]) -> Origin | None:
    """Return the single origin, or reject a batch that mixes origins."""
    origins = {record.origin for record in records}
    if len(origins) > 1:
        raise ValueError("A batch must not mix real-sandbox and synthetic records.")
    return next(iter(origins), None)


@dataclass(frozen=True)
class RealObservationSource:
    """Read-only adapter from the sandbox client to the shared source protocol."""

    client: SandboxClient

    def observations(self) -> Iterator[SourceRecord]:
        for page in self.client.pages("Observation"):
            yield from (SourceRecord(resource, "real-sandbox") for resource in page)
