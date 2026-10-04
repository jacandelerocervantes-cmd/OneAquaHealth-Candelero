"""Which sandbox Observations count as official OneAquaHealth records.

The public sandbox is shared: next to the consortium's records it holds demo records, simulated records and
records written under third-party profiles (forecast or citizen-science applications). None of these may
reach a count, an index or a QC finding. ``classify_official_record`` is the single documented decision and
``split_official`` applies it to a batch; see ``docs/official_record_filter.md``.

Rules, in priority order (the first one that applies is the reason reported):

1. ``meta.tag`` holds a coding whose ``code`` is ``simulated``, ``demo`` or ``synthetic``
   -> ``tag-simulated``, ``tag-demo``, ``tag-synthetic``.
2. A profile URL, a coding system or a coding code names a third-party application (``streampulse``,
   ``streamsense`` anywhere, or ``sl-`` as the start of a code or of the last segment of a profile or system)
   -> ``third-party``.
3. No ``meta.profile`` at all -> ``no-profile``.
4. No profile is an OAH profile (a URL under ``OAH_PROFILE_PREFIX``, or one of the bare profile names already
   used by ``oah.indices.water_parameter_limits``) -> ``non-oah-profile``.

Otherwise the record is official. The third-party markers come from the maintainer's inventory of the
sandbox (2026-10-02, ``docs/indices_catalog.md``); they are PROVISIONAL because the markers could not be
checked against every sandbox record here. Extend ``THIRD_PARTY_MARKERS`` when a new application appears.
Pure module: no I/O.
"""

from __future__ import annotations

from typing import Any, Sequence

from oah.indices.water_parameter_limits import HEALTH_MEASURE_PROFILES, WATER_PROFILES

OAH_PROFILE_PREFIX = "http://hl7.eu/fhir/ig/oah/StructureDefinition/"
EXCLUDED_TAG_CODES = ("simulated", "demo", "synthetic")
THIRD_PARTY_SUBSTRINGS = ("streampulse", "streamsense")
THIRD_PARTY_PREFIXES = ("sl-",)
THIRD_PARTY_MARKERS = THIRD_PARTY_SUBSTRINGS + THIRD_PARTY_PREFIXES  # documented inventory, provisional

EXCLUSION_REASONS = (
    "tag-simulated",
    "tag-demo",
    "tag-synthetic",
    "third-party",
    "no-profile",
    "non-oah-profile",
)
_BARE_OAH_PROFILES = WATER_PROFILES | HEALTH_MEASURE_PROFILES


def _text(value: Any) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


def _is_third_party_text(text: str) -> bool:
    if not text:
        return False
    if any(marker in text for marker in THIRD_PARTY_SUBSTRINGS):
        return True
    last_segment = text.rstrip("/").rsplit("/", 1)[-1]
    return any(last_segment.startswith(prefix) or text.startswith(prefix) for prefix in THIRD_PARTY_PREFIXES)


def _codings(observation: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    code = observation.get("code")
    if isinstance(code, dict):
        found.extend(c for c in code.get("coding") or [] if isinstance(c, dict))
    for component in observation.get("component") or []:
        inner = component.get("code") if isinstance(component, dict) else None
        if isinstance(inner, dict):
            found.extend(c for c in inner.get("coding") or [] if isinstance(c, dict))
    return found


def _is_oah_profile(profile: str) -> bool:
    return profile.startswith(OAH_PROFILE_PREFIX) or profile in _BARE_OAH_PROFILES


def classify_official_record(observation: dict[str, Any]) -> tuple[bool, str | None]:
    """``(True, None)`` for an official record, else ``(False, reason)`` with a value of ``EXCLUSION_REASONS``."""
    raw_meta = observation.get("meta")
    meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
    tag_codes = {_text(tag.get("code")) for tag in meta.get("tag") or [] if isinstance(tag, dict)}
    for code in EXCLUDED_TAG_CODES:
        if code in tag_codes:
            return False, f"tag-{code}"

    profiles: Sequence[Any] = [p for p in meta.get("profile") or [] if isinstance(p, str) and p.strip()]
    if any(_is_third_party_text(_text(p)) for p in profiles) or any(
        _is_third_party_text(_text(c.get("system"))) or _is_third_party_text(_text(c.get("code")))
        for c in _codings(observation)
    ):
        return False, "third-party"
    if not profiles:
        return False, "no-profile"
    if not any(_is_oah_profile(p.strip()) for p in profiles):
        return False, "non-oah-profile"
    return True, None


def split_official(observations: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """The official records of a batch, and how many were excluded per reason (every reason is present)."""
    official: list[dict[str, Any]] = []
    excluded = {reason: 0 for reason in EXCLUSION_REASONS}
    for observation in observations:
        keep, reason = classify_official_record(observation)
        if keep:
            official.append(observation)
        elif reason is not None:
            excluded[reason] += 1
    return official, excluded
