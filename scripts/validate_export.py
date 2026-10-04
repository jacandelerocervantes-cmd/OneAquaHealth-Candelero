"""Validate the generated findings Bundle with the official HL7 validator."""
from __future__ import annotations

from oah.fhir.official_validator import validate
from oah.fhir.validation_report import (
    build_export_validation_markdown,
    distinct_warning_error_messages,
    severity_counts,
)
from oah.paths import export_path, ig_build_path, qc_report_path


def main() -> None:
    findings_bundle = export_path("findings-bundle.json")
    issues = validate(
        [findings_bundle],
        ig_build_path("fsh-generated", "resources"),
        qc_report_path("export-validator-output.json"),
    )
    report = qc_report_path("export-validation-report.md")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(build_export_validation_markdown(issues), encoding="utf-8")
    print(severity_counts(issues))
    for severity, code, message in distinct_warning_error_messages(issues):
        print(f"{severity} [{code}]: {message}")
    print(report)
    if any(issue.severity in {"fatal", "error"} for issue in issues):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
