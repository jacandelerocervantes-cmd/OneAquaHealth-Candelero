"""Non-mutating statistical and unit quality-control rules."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    resource_id: str
    path: str
    message: str

def check_statistics(statistics: dict[str, float], path: str = "component") -> list[Finding]:
    findings: list[Finding] = []
    minimum = statistics.get("minimum")
    median = statistics.get("median")
    maximum = statistics.get("maximum")
    mean = statistics.get("average")
    if minimum is not None and maximum is not None and minimum > maximum:
        findings.append(Finding("statistical-bounds", "error", "", path, "minimum <= maximum is required."))
    if minimum is not None and median is not None and maximum is not None and not minimum <= median <= maximum:
        findings.append(Finding("statistical-order", "error", "", path, "minimum <= median <= maximum is required."))
    if minimum is not None and mean is not None and maximum is not None and not minimum <= mean <= maximum:
        findings.append(Finding("mean-range", "error", "", path, "minimum <= average <= maximum is required."))
    return findings

def check_unit(quantity: dict[str, Any], allowed_ucum: set[str], path: str = "valueQuantity") -> list[Finding]:
    if quantity.get("system") != "http://unitsofmeasure.org":
        return [Finding("ucum-system", "error", "", path, "Quantity system must be UCUM.")]
    if quantity.get("code") not in allowed_ucum:
        return [Finding("ucum-unit", "error", "", path, "Quantity.code is not an allowed UCUM code.")]
    return []

def censored_quantities(observation: dict[str, Any]) -> list[Finding]:
    """Flag Quantities carrying a comparator: they are bounds, not exact measurements."""
    identifier = observation.get("id", "unknown")
    paths = [("valueQuantity", observation.get("valueQuantity"))]
    paths += [(f"component[{i}].valueQuantity", c.get("valueQuantity")) for i, c in enumerate(observation.get("component", []))]
    return [
        Finding("censored-quantity", "warning", identifier, path, f"Quantity has comparator {quantity['comparator']!r}; it is not an exact value.")
        for path, quantity in paths
        if isinstance(quantity, dict) and quantity.get("comparator")
    ]

def component_statistics(observation: dict[str, Any], allowed_ucum: set[str]) -> list[Finding]:
    identifier = observation.get("id", "unknown")
    values: dict[str, float] = {}
    findings: list[Finding] = []
    for index, component in enumerate(observation.get("component", [])):
        coding = component.get("code", {}).get("coding", [])
        code = next((item.get("code") for item in coding if item.get("code") in {"minimum", "maximum", "median", "average"}), None)
        quantity = component.get("valueQuantity", {})
        if code and isinstance(quantity.get("value"), (int, float)) and not isinstance(quantity["value"], bool):
            values[code] = quantity["value"]
            findings.extend(check_unit(quantity, allowed_ucum, f"component[{index}].valueQuantity"))
    combined = check_statistics(values) + findings
    return [Finding(item.code, item.severity, identifier, item.path, item.message) for item in combined] + censored_quantities(observation)

def check_range(value: float, lower: float | None, upper: float | None, path: str) -> list[Finding]:
    if (lower is not None and value < lower) or (upper is not None and value > upper):
        return [Finding("physical-range", "error", "", path, "Value is outside the configured physical range.")]
    return []
