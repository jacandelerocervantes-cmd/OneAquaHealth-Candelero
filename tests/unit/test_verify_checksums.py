"""Checksum verification edge cases."""

from __future__ import annotations

import hashlib

from oah import verify_checksums


def _reference_file(tmp_path, name: str, content: bytes) -> str:
    (tmp_path / name).write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def _use_reference_directory(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(verify_checksums, "reference_path", lambda *parts: tmp_path.joinpath(*parts))


def test_verify_ignores_blank_checksum_lines(monkeypatch, tmp_path) -> None:
    _use_reference_directory(monkeypatch, tmp_path)
    digest = _reference_file(tmp_path, "official.bin", b"official")
    (tmp_path / "CHECKSUMS.sha256").write_text(f"\n# official input\n{digest}  official.bin\n\n")
    assert verify_checksums.verify() == []


def test_verify_reports_unlisted_reference_file(monkeypatch, tmp_path) -> None:
    _use_reference_directory(monkeypatch, tmp_path)
    digest = _reference_file(tmp_path, "official.bin", b"official")
    _reference_file(tmp_path, "unexpected.bin", b"unexpected")
    (tmp_path / "CHECKSUMS.sha256").write_text(f"{digest}  official.bin\n")
    assert verify_checksums.verify() == ["unlisted: unexpected.bin"]


def test_verify_reports_hash_mismatch(monkeypatch, tmp_path) -> None:
    _use_reference_directory(monkeypatch, tmp_path)
    _reference_file(tmp_path, "official.bin", b"official")
    (tmp_path / "CHECKSUMS.sha256").write_text("0" * 64 + "  official.bin\n")
    assert verify_checksums.verify() == ["hash mismatch: official.bin"]
