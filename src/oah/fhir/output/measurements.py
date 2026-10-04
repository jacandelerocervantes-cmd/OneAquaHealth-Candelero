"""FHIR R4 collection Bundle of the measurements of ONE site (``GET /sites/{location_id}/fhir``).

Built from the very records ``GET /sites/{location_id}/measurements`` returns, so the two views never disagree. Rules
(docs/fhir_mapping.md, section "Site measurements export"):

* No code is invented. A parameter is written as text only (``code.text``, no ``coding``); a UCUM unit code is added only
  for units whose Waterbase or sandbox spelling is a valid UCUM code as written.
* Records without a numeric value are left out (never filled in). A Bundle with no Observation is refused by the route.
* Every resource carries the project-defined data-origin tag of the record (``real-eea-waterbase``, ``real-sandbox``);
  the Bundle is tagged ``real-derived`` like every other output of this module.
* One software ``Device`` and one ``Provenance`` (targets: every Observation; source: the attribution of the data) are
  included; ids are deterministic (UUID5), so the same input gives the same Bundle except for the retrieval time.
* It makes no claim of conformance to the OneAquaHealth profiles: those apply to the derived indicators of
  ``oah.fhir.output.export``. Structural validity (FHIR R4B) is tested in ``tests/unit/test_fhir_measurements.py``.
"""
from __future__ import annotations

from html import escape
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from oah.fhir.output.builders import ORIGIN_SYSTEM, bundle, software_device

LOCATION_ID_SYSTEM = "https://oneaquahealth-hackathon.example/location-id"
UCUM_SYSTEM = "http://unitsofmeasure.org"
# Units whose spelling in the Waterbase and sandbox records is already a valid UCUM code.
UCUM_UNITS = frozenset({"mg/L", "ug/L", "Cel", "%", "mS/cm", "uS/cm", "mg{P}/L", "mg{N}/L", "mg{NO3}/L", "mg{NH4}/L", "mg{NO2}/L"})
COMPARATORS = frozenset({"<", "<=", ">=", ">"})
SOFTWARE_NAME = "OneAquaHealth API"
SOFTWARE_VERSION = "0.1.0"
SCREENING_NOTE = "Reference values are screening aids, not legal limits."
_XHTML = '<div xmlns="http://www.w3.org/1999/xhtml">{}</div>'


class NoValuesError(ValueError):
    """The selection holds no record with a numeric value, so there is nothing to export."""


def _stable(*parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, "|".join(str(part) for part in parts)))


def _effective(record: dict[str, Any]) -> dict[str, Any]:
    start, end = record.get("period_start"), record.get("period_end")
    if start and end and start != end:
        return {"effectivePeriod": {"start": str(start), "end": str(end)}}
    single = start or end
    if single:
        return {"effectiveDateTime": str(single)}
    year, month = record.get("year"), record.get("month")
    if year:
        return {"effectiveDateTime": f"{year}-{int(month):02d}" if month else str(year)}
    return {}


def _note(record: dict[str, Any]) -> str:
    parts: list[str] = []
    if record.get("statistic"):
        parts.append(f"Statistic: {record['statistic']}")
    if record.get("n") is not None:
        parts.append(f"n={record['n']}")
    if record.get("min") is not None and record.get("max") is not None:
        parts.append(f"observed range {record['min']} to {record['max']}")
    if record.get("n_below_loq"):
        parts.append(f"{record['n_below_loq']} below the limit of quantification (not in the value)")
    parts.append(f"Reference check: {record.get('status')}")
    if record.get("limit") is not None:
        basis = f" ({record['limit_basis']})" if record.get("limit_basis") else ""
        parts.append(f"reference value {record['limit']} {record.get('limit_unit') or record.get('unit')}{basis}")
    parts.append(SCREENING_NOTE)
    return "; ".join(parts)


def _observation(record: dict[str, Any], location_id: str, location_uuid: str, location_name: str) -> dict[str, Any]:
    quantity: dict[str, Any] = {"value": record["value"], "unit": record["unit"]}
    if record.get("comparator") in COMPARATORS:
        quantity["comparator"] = record["comparator"]
    if record["unit"] in UCUM_UNITS:
        quantity["system"] = UCUM_SYSTEM
        quantity["code"] = record["unit"]
    summary = f"{record['parameter']}: {record.get('comparator') or ''}{record['value']} {record['unit']}"
    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "id": _stable(
            location_id, record["parameter"], record.get("period_start"), record.get("period_end"), record.get("year"),
            record.get("month"), record.get("statistic"), record.get("matrix"), record["unit"],
        ),
        "meta": {"tag": [{"system": ORIGIN_SYSTEM, "code": record.get("origin") or "real-derived"}]},
        "text": {"status": "generated", "div": _XHTML.format(escape(summary))},
        "status": "final",
        "code": {"text": record["parameter"]},
        "subject": {"reference": f"urn:uuid:{location_uuid}", "display": location_name},
        "valueQuantity": quantity,
        "note": [{"text": _note(record)}],
    }
    resource.update(_effective(record))
    return resource


def measurements_bundle(payload: dict[str, Any], retrieved: str) -> dict[str, Any]:
    """The Bundle for a ``GET /sites/{id}/measurements`` payload; ``retrieved`` is an ISO UTC timestamp."""
    location_id = str(payload["location_id"])
    site = payload.get("site") or {}
    name = str(site.get("name") or location_id)
    location_uuid = _stable("Location", location_id)
    location: dict[str, Any] = {
        "resourceType": "Location",
        "id": location_uuid,
        "meta": {"tag": [{"system": ORIGIN_SYSTEM, "code": payload.get("origin") or "real-derived"}]},
        "text": {"status": "generated", "div": _XHTML.format(escape(name))},
        "identifier": [{"system": LOCATION_ID_SYSTEM, "value": location_id}],
        "name": name,
        "mode": "instance",
    }
    latitude, longitude = site.get("latitude"), site.get("longitude")
    if latitude is not None and longitude is not None:
        location["position"] = {"longitude": longitude, "latitude": latitude}

    observations = [
        _observation(record, location_id, location_uuid, name)
        for record in payload.get("records", [])
        if isinstance(record.get("value"), (int, float))
    ]
    if not observations:
        raise NoValuesError("No measurement with a numeric value for this selection.")
    # The same measurement can appear twice only if the records repeat; keep one Observation per id.
    unique = list({obs["id"]: obs for obs in observations}.values())

    device = software_device(SOFTWARE_NAME, SOFTWARE_VERSION)
    source = payload.get("attribution") or str(payload.get("origin"))
    provenance = {
        "resourceType": "Provenance",
        "id": _stable("Provenance", location_id, retrieved, *[obs["id"] for obs in unique]),
        "meta": {"tag": [{"system": ORIGIN_SYSTEM, "code": payload.get("origin") or "real-derived"}]},
        "text": {"status": "generated", "div": _XHTML.format("Provenance of the measurements of one site")},
        "target": [{"reference": f"urn:uuid:{obs['id']}"} for obs in unique],
        "recorded": retrieved,
        "reason": [{"text": SCREENING_NOTE}],
        "agent": [{"who": {"reference": f"urn:uuid:{device['id']}"}}],
        "entity": [{"role": "source", "what": {"display": source}}],
    }
    return bundle([location, *unique, device, provenance])
