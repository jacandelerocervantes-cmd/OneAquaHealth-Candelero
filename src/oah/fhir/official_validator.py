"""Safe wrapper around the external HL7 FHIR validator CLI."""
from __future__ import annotations
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from oah.paths import tools_dir

@dataclass(frozen=True)
class ValidatorIssue:
    file: str
    severity: str
    code: str
    location: str
    message: str
    resource_id: str


def _resource_id(file_name: str) -> str:
    validated = Path(file_name)
    if not validated.is_file():
        return ""
    try:
        resource = json.loads(validated.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return resource.get("id", "")


def _outcome_issues(outcome: dict, file_name: str) -> list[ValidatorIssue]:
    resource_id = _resource_id(file_name)
    issues = []
    for issue in outcome.get("issue", []):
        details = issue.get("details", {}).get("text", "")
        expression = ", ".join(issue.get("expression", []))
        issues.append(
            ValidatorIssue(
                file_name,
                issue.get("severity", "unknown"),
                issue.get("code", ""),
                expression,
                details,
                resource_id,
            )
        )
    return issues

def validate(files: list[Path], ig_package: Path, output: Path, timeout: int = 600) -> list[ValidatorIssue]:
    metadata = [file for file in files if file.name.endswith(".metadata.json")]
    if metadata:
        raise ValueError("Validator inputs must not include fixture metadata sidecars.")
    java = shutil.which("java")
    jar = tools_dir().joinpath("validator_cli.jar")
    if not java:
        raise RuntimeError("Java is required for the official HL7 validator.")
    if not jar.is_file():
        raise RuntimeError("HL7 validator jar is missing from OAH_TOOLS_DIR.")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    command = [java, "-jar", str(jar), *(str(file) for file in files), "-version", "4.0.1", "-ig", str(ig_package), "-locale", "en", "-output", str(output)]
    try:
        result = subprocess.run(command, check=False, timeout=timeout, capture_output=True, text=True)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Official validator timed out.") from error
    if not output.is_file():
        tail = (result.stdout + result.stderr)[-2000:]
        raise RuntimeError(f"Validator produced no output (exit {result.returncode}): {tail}")
    validator_output = json.loads(output.read_text(encoding="utf-8"))
    issues = []
    if (
        validator_output.get("resourceType") == "Bundle"
        and validator_output.get("type") == "collection"
    ):
        for entry in validator_output.get("entry", []):
            outcome = entry.get("resource", {})
            if outcome.get("resourceType") != "OperationOutcome":
                continue
            file_name = next(
                (
                    item.get("valueString", "")
                    for item in outcome.get("extension", [])
                    if item.get("url")
                    == "http://hl7.org/fhir/StructureDefinition/operationoutcome-file"
                ),
                "",
            )
            issues.extend(_outcome_issues(outcome, file_name))
    elif validator_output.get("resourceType") == "OperationOutcome" and len(files) == 1:
        issues.extend(_outcome_issues(validator_output, str(files[0])))
    else:
        raise RuntimeError("Validator output is not an accepted OperationOutcome shape.")
    if not issues and result.returncode != 0:
        raise RuntimeError("Validator failed without issues.")
    return issues
