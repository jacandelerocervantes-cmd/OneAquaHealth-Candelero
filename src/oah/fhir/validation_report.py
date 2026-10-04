"""Pure selection and Markdown reporting for official FHIR validation."""
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from typing import Any

OBSERVATION_WITH_COMPONENT_PROFILE = (
    "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"
)
OBSERVATION_HEALTH_MEASURE_PROFILE = (
    "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-health-measure-oah"
)
OBSERVATION_INDICATORS_PROFILE = (
    "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-indicators-oah"
)
SAMPLE_LIMITS = (
    (OBSERVATION_WITH_COMPONENT_PROFILE, 7),
    (OBSERVATION_HEALTH_MEASURE_PROFILE, 7),
    (OBSERVATION_INDICATORS_PROFILE, 6),
)


def _canonical_resource(resource: dict[str, Any]) -> str:
    return json.dumps(resource, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sample_profile(resource: dict[str, Any]) -> str | None:
    profiles = resource.get("meta", {}).get("profile", [])
    return next((profile for profile, _ in SAMPLE_LIMITS if profile in profiles), None)


def select_validation_sample(observations: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a deterministic, profile-balanced Observation sample."""
    ordered = sorted(observations, key=_canonical_resource)
    selected: list[dict[str, Any]] = []
    for profile, limit in SAMPLE_LIMITS:
        matches = (resource for resource in ordered if _sample_profile(resource) == profile)
        selected.extend(list(matches)[:limit])
    return selected


def build_report(issues, profiles):
    """Aggregate validator issues and selected profile occurrences."""
    severities = Counter(issue.severity for issue in issues)
    messages = Counter(issue.message for issue in issues)
    files = Counter(issue.file for issue in issues)
    return {
        "severity_counts": dict(severities),
        "profile_counts": dict(Counter(profiles)),
        "top_messages": messages.most_common(10),
        "file_counts": dict(files),
    }


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _table(title: str, headers: tuple[str, str], rows: Iterable[tuple[object, object]]) -> list[str]:
    lines = [f"## {title}", "", f"| {headers[0]} | {headers[1]} |", "| --- | ---: |"]
    lines.extend(f"| {_cell(key)} | {_cell(value)} |" for key, value in rows)
    return lines + [""]


def build_markdown_report(report: dict[str, Any]) -> str:
    """Render an official-validator report in readable Markdown."""
    lines = ["# Official validation report", ""]
    lines.extend(
        _table("Severity", ("Severity", "Count"), sorted(report["severity_counts"].items()))
    )
    lines.extend(
        _table("Profiles", ("Profile", "Selected"), sorted(report["profile_counts"].items()))
    )
    lines.extend(_table("Top 10 messages", ("Message", "Count"), report["top_messages"]))
    lines.extend(_table("Files", ("File", "Issues"), sorted(report["file_counts"].items())))
    return "\n".join(lines)


def severity_counts(issues) -> dict[str, int]:
    """Count official-validator issues by severity."""
    return dict(Counter(issue.severity for issue in issues))


def distinct_warning_error_messages(issues) -> list[tuple[str, str, str]]:
    """Return sorted distinct warning, error, and fatal issue descriptions."""
    messages = {
        (issue.severity, issue.code, issue.message)
        for issue in issues
        if issue.severity in {"warning", "error", "fatal"}
    }
    return sorted(messages)


def build_export_validation_markdown(issues) -> str:
    """Render the single exported-Bundle validation result as Markdown."""
    lines = ["# Exported findings Bundle validation", ""]
    lines.extend(_table("Severity", ("Severity", "Count"), sorted(severity_counts(issues).items())))
    lines.extend(["## Distinct warnings and errors", ""])
    messages = distinct_warning_error_messages(issues)
    if messages:
        lines.extend(f"- {severity} [{code}]: {message}" for severity, code, message in messages)
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"
