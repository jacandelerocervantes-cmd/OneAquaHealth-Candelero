"""Verified implementation-guide extraction contracts."""

from __future__ import annotations

from zipfile import ZipFile

import pytest

from oah import extract_ig


def _archive(tmp_path, members: dict[str, bytes]) -> None:
    with ZipFile(tmp_path / "oah-master.zip", "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def _paths(monkeypatch, tmp_path) -> None:
    output = tmp_path / "ig"
    monkeypatch.setattr(extract_ig, "reference_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr(extract_ig, "ig_path", lambda *parts: output.joinpath(*parts))


def test_extract_refuses_bad_hash(monkeypatch, tmp_path) -> None:
    _paths(monkeypatch, tmp_path)
    monkeypatch.setattr(extract_ig, "verify", lambda: ["hash mismatch: oah-master.zip"])
    with pytest.raises(RuntimeError, match="unverified reference"):
        extract_ig.extract()


def test_extract_rejects_parent_traversal_member(monkeypatch, tmp_path) -> None:
    _paths(monkeypatch, tmp_path)
    _archive(tmp_path, {"oah-master/input/../escape.fsh": b"invalid"})
    monkeypatch.setattr(extract_ig, "verify", lambda: [])
    with pytest.raises(RuntimeError, match="Unsafe archive member"):
        extract_ig.extract()


def test_extract_includes_config_and_models(monkeypatch, tmp_path) -> None:
    _paths(monkeypatch, tmp_path)
    _archive(
        tmp_path,
        {
            "oah-master/sushi-config.yaml": b"id: oah",
            "oah-master/models-src/models.xlsx": b"model",
            "oah-master/input/fsh/profile.fsh": b"Profile: Example",
            "oah-master/_samples/retained.csv": b"sample",
        },
    )
    monkeypatch.setattr(extract_ig, "verify", lambda: [])
    assert extract_ig.extract() == 3
    output = tmp_path / "ig"
    assert (output / "sushi-config.yaml").read_bytes() == b"id: oah"
    assert (output / "models-src" / "models.xlsx").read_bytes() == b"model"
    assert not (output / "_samples").exists()
