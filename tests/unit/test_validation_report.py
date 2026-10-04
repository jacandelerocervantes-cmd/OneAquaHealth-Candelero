from oah.fhir.official_validator import ValidatorIssue
from oah.fhir.validation_report import (
    OBSERVATION_HEALTH_MEASURE_PROFILE,
    OBSERVATION_INDICATORS_PROFILE,
    OBSERVATION_WITH_COMPONENT_PROFILE,
    build_markdown_report,
    build_export_validation_markdown,
    build_report,
    select_validation_sample,
)

def test_report_counts_canned_issues():
    issue = ValidatorIssue("file", "warning", "code", "path", "message", "id")
    report = build_report([issue], ["profile"])
    assert report["severity_counts"] == {"warning": 1}
    assert report["file_counts"] == {"file": 1}


def test_sample_is_deterministic_and_limited_by_profile():
    observations = [
        {
            "resourceType": "Observation",
            "id": f"component-{index}",
            "meta": {"profile": [OBSERVATION_WITH_COMPONENT_PROFILE]},
        }
        for index in range(8)
    ]
    observations.extend(
        {
            "resourceType": "Observation",
            "id": f"health-{index}",
            "meta": {"profile": [OBSERVATION_HEALTH_MEASURE_PROFILE]},
        }
        for index in range(8)
    )
    observations.extend(
        {
            "resourceType": "Observation",
            "id": f"indicator-{index}",
            "meta": {"profile": [OBSERVATION_INDICATORS_PROFILE]},
        }
        for index in range(7)
    )
    selected = select_validation_sample(list(reversed(observations)))
    profiles = [profile for resource in selected for profile in resource["meta"]["profile"]]
    assert selected == select_validation_sample(observations)
    assert profiles.count(OBSERVATION_WITH_COMPONENT_PROFILE) == 7
    assert profiles.count(OBSERVATION_HEALTH_MEASURE_PROFILE) == 7
    assert profiles.count(OBSERVATION_INDICATORS_PROFILE) == 6


def test_markdown_report_has_all_requested_tables():
    issue = ValidatorIssue("input.json", "warning", "code", "path", "message | text", "id")
    markdown = build_markdown_report(build_report([issue], ["profile"]))
    assert "## Severity" in markdown
    assert "## Profiles" in markdown
    assert "## Top 10 messages" in markdown
    assert "## Files" in markdown
    assert "message \\| text" in markdown


def test_export_validation_markdown_deduplicates_warning_and_error_messages():
    issues = [
        ValidatorIssue("file", "warning", "code", "path", "warning text", "id"),
        ValidatorIssue("file", "warning", "code", "path", "warning text", "id"),
        ValidatorIssue("file", "error", "other", "path", "error text", "id"),
    ]
    markdown = build_export_validation_markdown(issues)
    assert "| error | 1 |" in markdown
    assert "| warning | 2 |" in markdown
    assert markdown.count("warning [code]: warning text") == 1
    assert "error [other]: error text" in markdown
