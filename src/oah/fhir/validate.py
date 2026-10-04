"""R4B structural validation plus explicitly derived OAH profile checks.

Profile checks are derived by hand from the FSH sources in ``ig/oah/input/fsh/profiles`` (see
docs/fhir_mapping.md). They are a fast, offline subset: the official HL7 validator run against the built IG
(``scripts/validate_official.py``, ``scripts/validate_all_real.py``) remains the conformance evidence.
References are checked by resource TYPE only; a ``urn:uuid`` or contained reference cannot be resolved here
and is not checked.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from fhir.resources.R4B.bundle import Bundle
from fhir.resources.R4B.detectedissue import DetectedIssue
from fhir.resources.R4B.device import Device
from fhir.resources.R4B.group import Group
from fhir.resources.R4B.library import Library
from fhir.resources.R4B.location import Location
from fhir.resources.R4B.observation import Observation
from fhir.resources.R4B.organization import Organization
from fhir.resources.R4B.provenance import Provenance
from fhir.resources.R4B.specimen import Specimen
from pydantic import BaseModel


@dataclass(frozen=True)
class ValidationFinding:
    code: str
    message: str
    path: str = ""


@dataclass(frozen=True)
class ValidationResult:
    findings: tuple[ValidationFinding, ...]
    applied_profiles: tuple[str, ...]


_PROFILE_BASE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/"
OAH_OBSERVATION_PROFILE = _PROFILE_BASE + "observation-with-component-oah"
OAH_LOCATION_PROFILE = _PROFILE_BASE + "location-oah"
OAH_INDICATORS_PROFILE = _PROFILE_BASE + "observation-indicators-oah"
OAH_HEALTH_MEASURE_PROFILE = _PROFILE_BASE + "observation-health-measure-oah"

STRUCTURAL_MODELS: dict[str, type[BaseModel]] = {
    "Bundle": Bundle,
    "DetectedIssue": DetectedIssue,
    "Device": Device,
    "Group": Group,
    "Library": Library,
    "Location": Location,
    "Observation": Observation,
    "Organization": Organization,
    "Provenance": Provenance,
    "Specimen": Specimen,
}

_EFFECTIVE_KEYS = ("effectiveDateTime", "effectivePeriod", "effectiveTiming", "effectiveInstant")
_VALUE_TYPES = ("valueCodeableConcept", "valueQuantity")  # value[x] of both indicator profiles
_COMPONENT_VALUE_TYPES = ("valueCodeableConcept", "valueString", "valueQuantity")  # indicators component


def _reference_type(reference: Any) -> str | None:
    """Resource type a Reference points to, or None when it cannot be told without resolving it."""
    if not isinstance(reference, dict):
        return None
    explicit = reference.get("type")
    if isinstance(explicit, str):
        return explicit
    target = reference.get("reference")
    if not isinstance(target, str) or target.startswith(("urn:", "#")):
        return None
    parts = [part for part in target.split("?")[0].split("/") if part]
    if "_history" in parts:
        parts = parts[: parts.index("_history")]
    return parts[-2] if len(parts) >= 2 else None


def _observation_findings(resource: dict[str, Any], prefix: str, indicators: bool) -> list[ValidationFinding]:
    """Constraints shared by ObservationIndicatorsOah and ObservationHealthMeasureOah (FSH-derived)."""
    findings: list[ValidationFinding] = []
    label = "ObservationIndicatorsOah" if indicators else "ObservationHealthMeasureOah"

    def add(suffix: str, message: str, path: str = "") -> None:
        findings.append(ValidationFinding(f"{prefix}-{suffix}", f"{label}: {message}", path))

    if resource.get("status") != "final":
        add("status", "status is fixed to final.", "status")
    if not resource.get("code"):
        add("code", "code is required.", "code")
    subject = resource.get("subject")
    if not subject:
        add("subject", "subject is required.", "subject")
    elif _reference_type(subject) not in (None, "Location"):
        add("subject-type", "subject must reference a Location (LocationOah).", "subject")
    if not any(key in resource for key in _EFFECTIVE_KEYS):
        add("effective", "effective[x] is required.", "effective[x]")
    for key in resource:
        if key.startswith("value") and key not in _VALUE_TYPES:
            add("value-type", f"value[x] must be CodeableConcept or Quantity, not {key}.", key)
    if indicators:
        if not resource.get("performer"):
            add("performer", "performer is required.", "performer")
        if "specimen" in resource and _reference_type(resource["specimen"]) not in (None, "Specimen"):
            add("specimen-type", "specimen must reference a Specimen (SpecimenOah).", "specimen")
        for index, component in enumerate(resource.get("component", [])):
            values = [key for key in component if key.startswith("value")]
            path = f"component[{index}]"
            if not values:
                add("component-value", "component.value[x] is required.", path)
            elif values[0] not in _COMPONENT_VALUE_TYPES:
                add("component-value-type", f"component.value[x] must be CodeableConcept, string or Quantity, not {values[0]}.", path)
    elif "focus" in resource:
        focus: Sequence[Any] = resource["focus"]
        if any(_reference_type(item) not in (None, "Group") for item in focus):
            add("focus-type", "focus must reference a Group (GroupOah).", "focus")
    return findings


def validate_resource(resource: dict[str, Any]) -> ValidationResult:
    findings: list[ValidationFinding] = []
    resource_type = resource.get("resourceType")
    model = STRUCTURAL_MODELS.get(resource_type) if isinstance(resource_type, str) else None
    if model is None:
        return ValidationResult(
            (ValidationFinding("unsupported-resource-type", f"Unsupported resource type: {resource_type}"),),
            (),
        )
    try:
        model.model_validate(resource)
    except Exception as error:
        findings.append(ValidationFinding("r4b-structure", str(error)))
    profiles = set(resource.get("meta", {}).get("profile", []))
    if OAH_LOCATION_PROFILE in profiles:
        if not resource.get("identifier"):
            findings.append(ValidationFinding("location-identifier", "LocationOah requires identifier."))
        if not resource.get("name"):
            findings.append(ValidationFinding("location-name", "LocationOah requires name."))
        if resource.get("mode") != "instance":
            findings.append(ValidationFinding("location-mode", "LocationOah fixes mode to instance."))
    if OAH_OBSERVATION_PROFILE in profiles:
        if any(key.startswith("value") for key in resource):
            findings.append(ValidationFinding("observation-value", "Profile prohibits value[x]."))
        if not resource.get("component"):
            findings.append(ValidationFinding("observation-component", "Profile requires component."))
    if OAH_INDICATORS_PROFILE in profiles:
        findings.extend(_observation_findings(resource, "indicators", indicators=True))
    if OAH_HEALTH_MEASURE_PROFILE in profiles:
        findings.extend(_observation_findings(resource, "health-measure", indicators=False))
    known = {OAH_LOCATION_PROFILE, OAH_OBSERVATION_PROFILE, OAH_INDICATORS_PROFILE, OAH_HEALTH_MEASURE_PROFILE}
    return ValidationResult(tuple(findings), tuple(sorted(profiles & known)))
