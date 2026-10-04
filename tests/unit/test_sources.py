"""Source-manifest schema and external-origin contract."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from oah.paths import repo_path


def _sources() -> list[dict[str, Any]]:
    manifest = yaml.safe_load(repo_path("SOURCES.yaml").read_text(encoding="utf-8"))
    return manifest["sources"]


def test_source_entries_use_normalized_origins_schema() -> None:
    for source in _sources():
        assert isinstance(source["origins"], list)
        assert source["origin_type"] in {"existing", "new", "reference"}


def test_existing_origins_exist_when_sources_root_is_configured() -> None:
    source_root = os.getenv("OAH_SOURCES_ROOT")
    if not source_root:
        pytest.skip("OAH_SOURCES_ROOT is not configured")
    root = Path(source_root)
    missing = [
        origin
        for source in _sources()
        for origin in source["origins"]
        if not (root / origin).is_dir()
    ]
    assert not missing, f"Missing source origins: {missing}"


def test_untagged_resource_is_rejected_without_a_declared_origin():
    import pytest

    from oah.ingest.sources import origin_from_resource, source_records

    with pytest.raises(ValueError, match="Untagged"):
        origin_from_resource({"resourceType": "Observation"})
    with pytest.raises(ValueError, match="Untagged"):
        source_records([{"resourceType": "Observation"}])


def test_declared_origin_labels_untagged_but_a_synthetic_tag_always_wins():
    from oah.ingest.sources import origin_from_resource

    untagged = {"resourceType": "Observation"}
    tagged = {"meta": {"tag": [{"code": "synthetic"}]}}
    assert origin_from_resource(untagged, "real-sandbox") == "real-sandbox"
    assert origin_from_resource(tagged, "real-sandbox") == "synthetic"
    assert origin_from_resource(tagged) == "synthetic"


def test_empty_qc_report_needs_a_declared_origin_and_is_not_silently_real():
    import pytest

    from oah.qc.report import build_report

    with pytest.raises(ValueError, match="empty batch"):
        build_report([])
    assert build_report([], default_origin="real-sandbox")["origin"] == "real-sandbox"
