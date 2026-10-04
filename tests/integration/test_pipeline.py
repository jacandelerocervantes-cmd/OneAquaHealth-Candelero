"""Integration test for scripts/run_pipeline.py against a small canned dataset.

No real network is used: the sandbox client is replaced with a fake that writes the same
snapshot file shape the real client would, so every downstream stage (which prefers a local
snapshot file over a live fetch) reads from disk. OAH_DATA_DIR is redirected to a pytest
tmp_path for the whole test via monkeypatch.setenv, so every path helper resolves under it
automatically without patching each one individually. The official (external-tool) HL7
validation stage is forced to its SKIPPED branch by hiding "java" from shutil.which, so the
test never depends on -- or is slowed down by -- whatever tools happen to be installed on the
machine running the suite.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest


def _canned_observations() -> list[dict]:
    return [
        {
            "id": "obs-nitrate-1",
            "resourceType": "Observation",
            "status": "final",
            "meta": {"profile": ["http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"]},
            "subject": {"reference": "Location/Loc-Test-01"},
            "code": {"coding": [{"code": "nitrate"}], "text": "Nitrate"},
            "valueQuantity": {"value": 12.0, "unit": "mg/L", "system": "http://unitsofmeasure.org", "code": "mg/L"},
        },
        {
            "id": "obs-ph-1",
            "resourceType": "Observation",
            "status": "final",
            "meta": {"profile": ["http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"]},
            "subject": {"reference": "Location/Loc-Test-01"},
            "code": {"coding": [{"code": "ph"}], "text": "pH"},
            "valueQuantity": {"value": 7.5, "unit": "pH", "system": "http://unitsofmeasure.org", "code": "[pH]"},
        },
    ]


class FakeSandboxClient:
    """Replaces oah.ingest.sandbox_client.SandboxClient for this test only."""

    def pages(self, resource_type: str):
        assert resource_type == "Observation"
        yield _canned_observations()

    def snapshot(self, resource_type: str) -> Path:
        from oah.paths import sandbox_snapshot_path

        target = sandbox_snapshot_path(resource_type)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(_canned_observations(), indent=2), encoding="utf-8")
        return target


@pytest.fixture()
def pipeline_module(tmp_path, monkeypatch):
    """Import scripts/run_pipeline.py fresh with OAH_DATA_DIR pointed at tmp_path."""
    monkeypatch.setenv("OAH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OAH_SANDBOX_URL", "https://sandbox.example.test/fhir")
    monkeypatch.setattr("shutil.which", lambda name: None)  # forces the optional stage to skip

    scripts_dir = str(Path(__file__).resolve().parents[2] / "scripts")
    added = scripts_dir not in sys.path
    if added:
        sys.path.insert(0, scripts_dir)
    try:
        if "run_pipeline" in sys.modules:
            del sys.modules["run_pipeline"]
        module = importlib.import_module("run_pipeline")
    finally:
        if added:
            sys.path.remove(scripts_dir)

    monkeypatch.setattr(module, "configured_client", lambda: FakeSandboxClient())
    return module


def test_pipeline_runs_every_mandatory_stage_and_writes_expected_files(pipeline_module, tmp_path, capsys):
    pipeline_module.main()

    output = capsys.readouterr().out
    assert "PIPELINE FAILED" not in output
    assert "SKIPPED" in output  # the official validator stage, deterministically forced off

    assert (tmp_path / "sandbox" / "Observation.json").is_file()
    assert (tmp_path / "reports" / "pipeline_qc_report.json").is_file()
    assert (tmp_path / "reports" / "pipeline_structural_validation.json").is_file()
    assert (tmp_path / "exports" / "pipeline-findings-bundle.json").is_file()
    assert (tmp_path / "reports" / "pipeline_indices_report.json").is_file()
    assert (tmp_path / "reports" / "pipeline_risk_report.json").is_file()

    qc = json.loads((tmp_path / "reports" / "pipeline_qc_report.json").read_text(encoding="utf-8"))
    assert qc["total_observations"] == 2

    risk = json.loads((tmp_path / "reports" / "pipeline_risk_report.json").read_text(encoding="utf-8"))
    assert risk["origin"] == "synthetic"
    assert risk["risk_by_site"]["Loc-Almyros"] == 1.0


def test_pipeline_stops_immediately_on_a_mandatory_stage_failure(pipeline_module, monkeypatch, capsys):
    def broken_build_report(*args, **kwargs):
        raise RuntimeError("simulated QC failure")

    monkeypatch.setattr(pipeline_module, "build_report", broken_build_report)

    with pytest.raises(SystemExit) as excinfo:
        pipeline_module.main()
    assert excinfo.value.code == 1

    output = capsys.readouterr()
    assert "PIPELINE FAILED" in output.err
    assert "QC stage failed" in output.err
    assert "simulated QC failure" in output.err
    # Stages after the failing one must never have started.
    assert "[3/6]" not in output.out
    assert "[5/6]" not in output.out
