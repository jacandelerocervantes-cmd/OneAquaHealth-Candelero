"""Builder for derived-indicator Observations conforming to ``observation-indicators-oah``.

The IG's code system has no concept for derived indices (CCME WQI, ...), and the profile binds
``code`` only *preferred*. Codes therefore come from a project-defined, explicitly provisional
CodeSystem; no IG or sandbox code is invented or reused for a different meaning.
"""
from __future__ import annotations

from html import escape
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from oah.fhir.output.builders import _tag

INDICATORS_PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-indicators-oah"
DERIVED_INDICATOR_SYSTEM = "https://oneaquahealth-hackathon.example/CodeSystem/derived-indicator"
PIPELINE_SYSTEM = "https://oneaquahealth-hackathon.example/pipeline-id"
PIPELINE_ID = "oneaquahealth-derived-indicators"
UCUM = "http://unitsofmeasure.org"

# code -> display; provisional, documented in docs/fhir_mapping.md
DERIVED_CODES: dict[str, str] = {
    "ccme-wqi": "CCME Water Quality Index 1.0 (derived)",
    "evaluable-measurements": "Number of evaluable measurements",
    "distinct-parameters": "Number of distinct parameters",
    "failed-measurements": "Number of measurements failing the objective limit",
    "worst-parameter-excursion": "Largest relative excursion of any parameter beyond its objective",
    "veto-status": "Non-compensatory veto status of the composite index",
}


def veto_status_text(evaluated: dict[str, Any]) -> str:
    """Return 'none', 'veto: <parameters>' or 'eclipsed: <parameters>' for an evaluated location."""
    if not evaluated.get("veto_triggered"):
        return "none"
    names = ", ".join(item["parameter"] for item in evaluated["veto_parameters"])
    return f"{'eclipsed' if evaluated.get('eclipsed') else 'veto'}: {names}"


def derived_code_system() -> dict[str, Any]:
    """Return the provisional CodeSystem resource that defines ``DERIVED_CODES``."""
    return _tag(
        {
            "resourceType": "CodeSystem",
            "id": str(uuid5(NAMESPACE_URL, DERIVED_INDICATOR_SYSTEM)),
            "url": DERIVED_INDICATOR_SYSTEM,
            "version": "0.1.0",
            "name": "DerivedIndicatorProvisional",
            "status": "draft",
            "experimental": True,
            "content": "complete",
            "caseSensitive": True,
            "description": "Provisional project-defined codes for indicators derived by this pipeline.",
            "concept": [{"code": code, "display": display} for code, display in sorted(DERIVED_CODES.items())],
        }
    )


def _count(code: str, value: int) -> dict[str, Any]:
    return {
        "code": {"coding": [{"system": DERIVED_INDICATOR_SYSTEM, "code": code, "display": DERIVED_CODES[code]}]},
        "valueQuantity": {"value": value, "unit": "1", "system": UCUM, "code": "1"},
    }


def _veto_components(evaluated: dict[str, Any]) -> list[dict[str, Any]]:
    if "veto_triggered" not in evaluated:
        return []
    return [
        {
            "code": {"coding": [{"system": DERIVED_INDICATOR_SYSTEM, "code": "worst-parameter-excursion", "display": DERIVED_CODES["worst-parameter-excursion"]}]},
            "valueQuantity": {"value": evaluated["worst_parameter_excursion"], "unit": "1", "system": UCUM, "code": "1"},
        },
        {
            "code": {"coding": [{"system": DERIVED_INDICATOR_SYSTEM, "code": "veto-status", "display": DERIVED_CODES["veto-status"]}]},
            "valueString": veto_status_text(evaluated),
        },
    ]


def ccme_wqi_observation(evaluated: dict[str, Any], location_url: str, effective: str, rule_version: str) -> dict[str, Any]:
    """Build one OAH-indicators Observation from an ``apply_ccme_wqi_to_sandbox`` evaluated entry."""
    from oah.indices.regimes import INTERPRETATION_NOTICE
    from oah.indices.water_quality import classify_ccme_wqi

    score = evaluated["ccme_wqi"]
    note = evaluated.get("confidence_note") or "normal confidence"
    label = classify_ccme_wqi(score)
    return _tag(
        {
            "text": {
                "status": "generated",
                "div": (
                    '<div xmlns="http://www.w3.org/1999/xhtml">'
                    f"CCME Water Quality Index {score:.1f} ({label}) for {escape(location_url)}; "
                    "derived by OneAquaHealth from real sandbox Observations.</div>"
                ),
            },
            "resourceType": "Observation",
            "id": str(uuid5(NAMESPACE_URL, f"{location_url}:ccme-wqi:{effective}:{rule_version}")),
            "meta": {"profile": [INDICATORS_PROFILE]},
            "status": "final",
            "code": {
                "coding": [{"system": DERIVED_INDICATOR_SYSTEM, "code": "ccme-wqi", "display": DERIVED_CODES["ccme-wqi"]}],
                "text": "CCME Water Quality Index",
            },
            "subject": {"reference": location_url},
            "effectiveDateTime": effective,
            "performer": [
                {
                    "type": "Organization",
                    "identifier": {"system": PIPELINE_SYSTEM, "value": PIPELINE_ID},
                    "display": "OneAquaHealth derived-indicators pipeline",
                }
            ],
            "valueQuantity": {"value": score, "unit": "1", "system": UCUM, "code": "1"},
            "interpretation": [{"text": label}],
            "note": [{"text": f"Confidence: {evaluated['confidence']} ({note})."}, {"text": INTERPRETATION_NOTICE}],
            "component": [
                _count("evaluable-measurements", evaluated["evaluable_measurements"]),
                _count("distinct-parameters", evaluated["distinct_parameters_count"]),
                _count("failed-measurements", evaluated["failed_measurements"]),
                *_veto_components(evaluated),
            ],
        }
    )
