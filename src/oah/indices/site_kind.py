"""What kind of place a sandbox Location is, so the app does not draw an air station as a water body.

Deterministic rules, first match wins (documented in ``docs/api_routes.md``):

1. A Location type coding in ``WATER_BODY_TYPE_CODES`` (SNOMED CT 420531007 "River", seen on the real Almyros
   Location) -> ``water-body``. Not provisional.
2. The id, name or description contains an ``AIR_STATION_KEYWORDS`` word -> ``air-quality-station``.
   PROVISIONAL: a text rule, because the Location resources carry no type that says "air station".
3. The id, name or description contains a ``WATER_BODY_KEYWORDS`` word -> ``water-body``. PROVISIONAL: these
   words are taken from ids already seen in the sandbox (``Loc-Almyros-Estuary``, ``Loc-Almyros-Coast``,
   ``Loc-Giofyros-LowerReach``) and from the Almyros description ("stream segment").
4. A type coding in ``CITY_TYPE_CODES`` (SNOMED CT 288520005 "City environment", observed on the sandbox) ->
   ``city``.
5. Anything else -> ``other``.

No code is invented. Pure module: no I/O.
"""

from __future__ import annotations

import re
from typing import Any, Literal

SiteKind = Literal["water-body", "air-quality-station", "city", "other"]

WATER_BODY_TYPE_CODES = frozenset({"420531007"})
CITY_TYPE_CODES = frozenset({"288520005"})
AIR_STATION_KEYWORDS = ("air quality", "air-quality", "station")
WATER_BODY_KEYWORDS = ("river", "stream", "estuary", "coast", "reach", "lake", "creek")
_WORD = re.compile(r"[a-z0-9]+")


def _type_codes(location: dict[str, Any]) -> set[str]:
    codes: set[str] = set()
    for location_type in location.get("type") or []:
        for coding in (location_type or {}).get("coding") or []:
            codes.add(str(coding.get("code")))
    return codes


def _mentions(text: str, keywords: tuple[str, ...]) -> bool:
    """True when a keyword occurs as a whole word (or word sequence) of ``text`` (case-insensitive,
    camel-case aware)."""
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)  # "LowerReach" -> "Lower Reach"
    words = " ".join(_WORD.findall(spaced.lower()))
    return any(re.search(rf"\b{' '.join(_WORD.findall(keyword))}\b", words) for keyword in keywords)


def site_kind(location: dict[str, Any]) -> SiteKind:
    """The kind of one Location resource (see the module docstring for the rules)."""
    codes = _type_codes(location)
    if codes & WATER_BODY_TYPE_CODES:
        return "water-body"
    text = " ".join(str(location.get(key) or "") for key in ("id", "name", "description"))
    if _mentions(text, AIR_STATION_KEYWORDS):
        return "air-quality-station"
    if _mentions(text, WATER_BODY_KEYWORDS):
        return "water-body"
    if codes & CITY_TYPE_CODES:
        return "city"
    return "other"
