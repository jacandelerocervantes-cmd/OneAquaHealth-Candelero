import hashlib
import json
import pytest
from oah.fhir.validate import validate_resource
from oah.paths import fixtures_real_path
from oah.qc.statistics import component_statistics

def test_real_fixtures_are_labeled_and_validated():
    directory = fixtures_real_path()
    files = list(directory.glob("*.json")) if directory.is_dir() else []
    if not files:
        pytest.skip("Real fixtures have not been captured; run scripts/capture_fixtures.py.")
    for file in files:
        if file.name.endswith(".metadata.json"):
            continue
        resource = json.loads(file.read_text())
        metadata = json.loads(file.with_suffix(".metadata.json").read_text())
        assert metadata["sha256"] == hashlib.sha256(file.read_bytes()).hexdigest()
        assert metadata["origin"] == "real-sandbox"
        result = validate_resource(resource)
        assert result.findings == (), file.name  # Group and Library are structurally supported since 2026-09-26
        if resource.get("id") == "Obs-Almyros-AluminiumDissolved-2013":
            codes = {item.code for item in component_statistics(resource, {"ug/L"})}
            assert {"statistical-order", "mean-range"} <= codes
        if resource["resourceType"] == "Library":
            assert metadata["truncated"] is True
            assert "original_content_count" in metadata
