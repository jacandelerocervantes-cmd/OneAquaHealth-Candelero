from pathlib import Path
import json
import subprocess
import pytest
from oah.fhir import official_validator

def test_missing_java(monkeypatch, tmp_path):
    monkeypatch.setattr(official_validator.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="Java"):
        official_validator.validate([], tmp_path, tmp_path / "out.json")

def test_bundle_parser_and_command(monkeypatch, tmp_path):
    first = tmp_path / "one.json"
    second = tmp_path / "two.json"
    first.write_text(json.dumps({"resourceType": "Observation", "id": "one"}))
    second.write_text(json.dumps({"resourceType": "Location", "id": "two"}))
    output = tmp_path / "out.json"
    issues = [{"severity": "error", "code": "x", "details": {"text": "error"}}] + [{"severity": "warning", "code": "x", "details": {"text": "warning"}}] * 2 + [{"severity": "information", "code": "x", "details": {"text": "info"}}] * 8
    outcome = {"resourceType": "OperationOutcome", "extension": [{"url": "http://hl7.org/fhir/StructureDefinition/operationoutcome-file", "valueString": str(first)}], "issue": issues}
    bundle = {"resourceType": "Bundle", "type": "collection", "entry": [{"resource": outcome}]}
    monkeypatch.setattr(official_validator.shutil, "which", lambda _: "java")
    monkeypatch.setattr(official_validator, "tools_dir", lambda: tmp_path)
    (tmp_path / "validator_cli.jar").write_bytes(b"x")
    command = []

    def run(args, **kwargs):
        # The validator writes its own output; validate() deletes any old file first.
        command.extend(args)
        Path(args[args.index("-output") + 1]).write_text(json.dumps(bundle), encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(official_validator.subprocess, "run", run)
    result = official_validator.validate([first], tmp_path, output)
    assert [item.severity for item in result].count("error") == 1
    assert [item.severity for item in result].count("warning") == 2
    assert [item.severity for item in result].count("information") == 8
    assert result[0].file == str(first)
    assert result[0].resource_id == "one"
    assert "-version" in command
    assert "4.0.1" in command
    assert "-locale" in command
    assert "en" in command


# --- Error paths and safeguards (all mocked: no Java, no network) -----------------------


def _prepare(monkeypatch, tmp_path, run, with_jar=True):
    monkeypatch.setattr(official_validator.shutil, "which", lambda _: "java")
    monkeypatch.setattr(official_validator, "tools_dir", lambda: tmp_path)
    if with_jar:
        (tmp_path / "validator_cli.jar").write_bytes(b"x")
    monkeypatch.setattr(official_validator.subprocess, "run", run)


def _writes_output(payload, returncode=0):
    """Build a fake subprocess.run that writes `payload` to the -output path."""

    def run(args, **kwargs):
        target = Path(args[args.index("-output") + 1])
        text = payload if isinstance(payload, str) else json.dumps(payload)
        target.write_text(text, encoding="utf-8")
        return subprocess.CompletedProcess(args, returncode, "", "")

    return run


def _must_not_run(args, **kwargs):
    raise AssertionError("the validator subprocess must not be started")


def test_single_operation_outcome_requires_exactly_one_input(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path, _writes_output({"resourceType": "OperationOutcome"}))
    with pytest.raises(RuntimeError, match="accepted OperationOutcome shape"):
        official_validator.validate([], tmp_path, tmp_path / "out.json")


def test_single_operation_outcome_uses_the_input_file(monkeypatch, tmp_path):
    source = tmp_path / "findings-bundle.json"
    source.write_text(json.dumps({"resourceType": "Bundle", "id": "findings"}), encoding="utf-8")
    outcome = {
        "resourceType": "OperationOutcome",
        "issue": [
            {"severity": "warning", "code": "code-a", "details": {"text": "warning"}},
            {"severity": "error", "code": "code-b", "details": {"text": "error"}},
        ],
    }
    _prepare(monkeypatch, tmp_path, _writes_output(outcome))
    issues = official_validator.validate([source], tmp_path, tmp_path / "out.json")
    assert [issue.severity for issue in issues].count("warning") == 1
    assert [issue.severity for issue in issues].count("error") == 1
    assert {issue.file for issue in issues} == {str(source)}
    assert {issue.resource_id for issue in issues} == {"findings"}


def test_bundle_of_another_type_raises(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path, _writes_output({"resourceType": "Bundle", "type": "searchset"}))
    with pytest.raises(RuntimeError, match="accepted OperationOutcome shape"):
        official_validator.validate([], tmp_path, tmp_path / "out.json")


def test_unparseable_output_raises(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path, _writes_output("not json at all"))
    with pytest.raises(ValueError):
        official_validator.validate([], tmp_path, tmp_path / "out.json")


def test_missing_jar_raises(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path, _must_not_run, with_jar=False)
    with pytest.raises(RuntimeError, match="jar"):
        official_validator.validate([], tmp_path, tmp_path / "out.json")


def test_timeout_raises(monkeypatch, tmp_path):
    def run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs.get("timeout", 0))

    _prepare(monkeypatch, tmp_path, run)
    with pytest.raises(RuntimeError, match="timed out"):
        official_validator.validate([], tmp_path, tmp_path / "out.json")


def test_nonzero_exit_without_output_raises_with_tail(monkeypatch, tmp_path):
    def run(args, **kwargs):
        return subprocess.CompletedProcess(args, 3, "stdout tail", "stderr tail")

    _prepare(monkeypatch, tmp_path, run)
    with pytest.raises(RuntimeError) as error:
        official_validator.validate([], tmp_path, tmp_path / "out.json")
    assert "exit 3" in str(error.value)
    assert "stdout tail" in str(error.value)
    assert "stderr tail" in str(error.value)


def test_no_issues_with_failing_exit_code_raises(monkeypatch, tmp_path):
    bundle = {"resourceType": "Bundle", "type": "collection", "entry": []}
    _prepare(monkeypatch, tmp_path, _writes_output(bundle, returncode=1))
    with pytest.raises(RuntimeError, match="failed without issues"):
        official_validator.validate([], tmp_path, tmp_path / "out.json")


def test_metadata_sidecar_is_rejected_before_running(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path, _must_not_run)
    sidecar = tmp_path / "Observation-x.metadata.json"
    sidecar.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="sidecar"):
        official_validator.validate([sidecar], tmp_path, tmp_path / "out.json")


def test_ig_package_path_is_passed_to_the_validator(monkeypatch, tmp_path):
    captured = []
    bundle = {"resourceType": "Bundle", "type": "collection", "entry": []}
    inner = _writes_output(bundle)

    def run(args, **kwargs):
        captured.extend(args)
        return inner(args, **kwargs)

    _prepare(monkeypatch, tmp_path, run)
    ig = tmp_path / "ig-package"
    official_validator.validate([], ig, tmp_path / "out.json")
    assert captured[captured.index("-ig") + 1] == str(ig)


def test_unreadable_validated_file_gives_empty_resource_id(monkeypatch, tmp_path):
    outcome = {
        "resourceType": "OperationOutcome",
        "extension": [
            {
                "url": "http://hl7.org/fhir/StructureDefinition/operationoutcome-file",
                "valueString": str(tmp_path / "missing.json"),
            }
        ],
        "issue": [{"severity": "warning", "code": "x", "details": {"text": "w"}}],
    }
    bundle = {"resourceType": "Bundle", "type": "collection", "entry": [{"resource": outcome}]}
    _prepare(monkeypatch, tmp_path, _writes_output(bundle))
    issues = official_validator.validate([], tmp_path, tmp_path / "out.json")
    assert len(issues) == 1
    assert issues[0].resource_id == ""


def test_stale_output_from_a_previous_run_is_not_trusted(monkeypatch, tmp_path):
    stale = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "OperationOutcome",
                    "issue": [{"severity": "information", "code": "x", "details": {"text": "old"}}],
                }
            }
        ],
    }
    output = tmp_path / "out.json"
    output.write_text(json.dumps(stale), encoding="utf-8")

    def failing_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, "", "validator crashed")

    _prepare(monkeypatch, tmp_path, failing_run)
    with pytest.raises(RuntimeError):
        official_validator.validate([], tmp_path, output)
