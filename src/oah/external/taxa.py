"""The small, explicit list of GBIF taxon groups (``src/oah/external/data/gbif_taxa.json``).

The taxon keys are DISCOVERED values (GBIF ``species/match``), recorded with their match confidence and the date of
discovery; this loader never invents one. It refuses a file that does not satisfy the discovery rules: an ``ORDER`` or
``FAMILY`` rank, status ``ACCEPTED``, match type ``EXACT``, a positive integer key, unique ids and keys, and aliases
that name existing groups only.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import Any

from oah.paths import source_path

SUPPORTED_SCHEMA = 1
RANKS = ("ORDER", "FAMILY")
FACET_OF_RANK = {"ORDER": "ORDER_KEY", "FAMILY": "FAMILY_KEY"}  # the GBIF facet that counts records per taxon of that rank
_ID = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
MAX_GROUPS = 12  # the list is meant to stay small and explicit


class TaxaError(ValueError):
    """The taxon file is malformed or breaks the discovery rules."""


@dataclass(frozen=True)
class TaxonGroup:
    id: str
    name: str
    common_name: str
    rank: str
    usage_key: int
    confidence: int
    justification: str
    caveat: str

    @property
    def facet(self) -> str:
        return FACET_OF_RANK[self.rank]


@dataclass(frozen=True)
class TaxonCatalogue:
    discovered_on: date
    method: str
    selection_note: str
    groups: tuple[TaxonGroup, ...]
    aliases: dict[str, tuple[str, ...]]

    def group(self, group_id: str) -> TaxonGroup | None:
        return next((item for item in self.groups if item.id == group_id), None)

    def selectable(self) -> tuple[str, ...]:
        """Every value a caller may name: the group ids and the aliases."""
        return (*(item.id for item in self.groups), *self.aliases)

    def resolve(self, name: str | None) -> tuple[TaxonGroup, ...]:
        """The groups a ``group`` argument stands for (all of them when ``name`` is None); ``KeyError`` if unknown."""
        if name is None:
            return self.groups
        key = name.strip().lower()
        if key in self.aliases:
            return tuple(item for member in self.aliases[key] if (item := self.group(member)) is not None)
        found = self.group(key)
        if found is None:
            raise KeyError(name)
        return (found,)


def _text(entry: dict[str, Any], key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > 400:
        raise TaxaError(f"group field {key!r} must be a non-empty text of at most 400 characters")
    return value


def parse_catalogue(data: Any) -> TaxonCatalogue:
    if not isinstance(data, dict) or data.get("schema_version") != SUPPORTED_SCHEMA:
        raise TaxaError("the taxon file must be an object with schema_version 1")
    try:
        discovered = date.fromisoformat(str(data.get("discovered_on")))
    except ValueError as error:
        raise TaxaError("discovered_on must be an ISO date") from error
    raw_groups = data.get("groups")
    if not isinstance(raw_groups, list) or not 0 < len(raw_groups) <= MAX_GROUPS:
        raise TaxaError(f"groups must be a list of 1 to {MAX_GROUPS} entries")
    groups: list[TaxonGroup] = []
    for entry in raw_groups:
        if not isinstance(entry, dict):
            raise TaxaError("each group must be an object")
        group_id = _text(entry, "id")
        key, confidence = entry.get("usage_key"), entry.get("confidence")
        if not _ID.fullmatch(group_id):
            raise TaxaError(f"invalid group id {group_id!r}")
        if entry.get("rank") not in RANKS:
            raise TaxaError(f"{group_id}: rank must be one of {RANKS}")
        if entry.get("status") != "ACCEPTED" or entry.get("match_type") != "EXACT":
            raise TaxaError(f"{group_id}: only an ACCEPTED, EXACT match may be listed")
        if isinstance(key, bool) or not isinstance(key, int) or key <= 0:
            raise TaxaError(f"{group_id}: usage_key must be a positive integer")
        if isinstance(confidence, bool) or not isinstance(confidence, int) or not 0 <= confidence <= 100:
            raise TaxaError(f"{group_id}: confidence must be an integer from 0 to 100")
        groups.append(
            TaxonGroup(
                id=group_id, name=_text(entry, "name"), common_name=_text(entry, "common_name"),
                rank=str(entry["rank"]), usage_key=key, confidence=confidence,
                justification=_text(entry, "justification"), caveat=_text(entry, "caveat"),
            )
        )
    if len({item.id for item in groups}) != len(groups) or len({item.usage_key for item in groups}) != len(groups):
        raise TaxaError("group ids and usage keys must be unique")
    raw_aliases = data.get("aliases", {})
    if not isinstance(raw_aliases, dict):
        raise TaxaError("aliases must be an object")
    known = {item.id for item in groups}
    aliases: dict[str, tuple[str, ...]] = {}
    for alias, members in raw_aliases.items():
        if not isinstance(alias, str) or not _ID.fullmatch(alias) or alias in known:
            raise TaxaError(f"invalid alias {alias!r}")
        if not isinstance(members, list) or not members or any(m not in known for m in members):
            raise TaxaError(f"alias {alias!r} must list existing group ids")
        aliases[alias] = tuple(str(m) for m in members)
    method = data.get("method")
    note = data.get("selection_note")
    if not isinstance(method, str) or not isinstance(note, str):
        raise TaxaError("method and selection_note are required")
    return TaxonCatalogue(discovered, method, note, tuple(groups), aliases)


@lru_cache(maxsize=1)
def load_catalogue() -> TaxonCatalogue:
    path = source_path("external", "data", "gbif_taxa.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TaxaError(f"cannot read the taxon file ({type(error).__name__})") from error
    return parse_catalogue(data)
