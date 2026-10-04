"""Archived sample loading must not require extraction."""

from __future__ import annotations

from zipfile import ZipFile

import pytest

from oah.ingest import samples


def test_reads_sample_directly_from_verified_archive(monkeypatch, tmp_path) -> None:
    with ZipFile(tmp_path / "oah-master.zip", "w") as archive:
        archive.writestr("oah-master/_samples/example.csv", b"value\n1\n")
    calls = 0

    def verified() -> list[str]:
        nonlocal calls
        calls += 1
        return []

    samples._ensure_verified.cache_clear()
    monkeypatch.setattr(samples, "reference_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr(samples, "verify", verified)
    assert samples.sample_names() == ("example.csv",)
    assert samples.read_sample_bytes("example.csv") == b"value\n1\n"
    assert calls == 1


def test_rejects_sample_parent_traversal() -> None:
    with pytest.raises(ValueError, match="must not traverse"):
        samples._member_name(".." + "/outside.csv")
