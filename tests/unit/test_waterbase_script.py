"""The build command line: path resolution, clear failures, and one real run through 7-Zip when it is installed."""

from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path

import pytest
from waterbase_fixtures import make_archive

from oah.paths import repo_path, sevenzip_executable


@pytest.fixture()
def script():
    scripts_dir = str(repo_path("scripts"))
    sys.path.insert(0, scripts_dir)
    try:
        yield importlib.import_module("build_waterbase_store")
    finally:
        sys.path.remove(scripts_dir)
        sys.modules.pop("build_waterbase_store", None)


def test_the_dry_run_names_the_resolved_inputs_without_absolute_paths(script, tmp_path: Path, monkeypatch, capsys):
    fake = tmp_path / "7z-fake.exe"
    fake.write_bytes(b"")
    monkeypatch.setenv("OAH_SEVENZIP_PATH", str(fake))
    assert script.main(["--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "eea_t_waterbase-water-quality-icm-2026_p_1900-2025_v01_r00.zip (MISSING)" in output
    assert "waterbase_icm_2026.sqlite (new)" in output and "7z-fake.exe" in output and "min year: 2010" in output
    assert str(tmp_path) not in output  # file names only, never a local path


def test_a_missing_seven_zip_or_archive_is_a_clear_failure(script, tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("OAH_SEVENZIP_PATH", str(tmp_path / "missing-7z.exe"))
    assert script.main([]) == 2
    assert "7-Zip is required" in capsys.readouterr().err
    fake = tmp_path / "7z-fake.exe"
    fake.write_bytes(b"")
    monkeypatch.setenv("OAH_SEVENZIP_PATH", str(fake))
    assert script.main(["--archive", str(tmp_path / "absent.zip")]) == 2
    assert "archive is missing" in capsys.readouterr().err


def test_relative_paths_are_refused(script):
    with pytest.raises(RuntimeError, match="absolute"):
        script.main(["--archive", "relative/archive.zip", "--dry-run"])


@pytest.mark.skipif(sevenzip_executable() is None, reason="7-Zip is not installed on this machine")
def test_a_full_run_builds_a_store_the_reader_accepts(script, tmp_path: Path, monkeypatch, capsys):
    executable = sevenzip_executable()
    assert executable is not None
    monkeypatch.setenv("OAH_SEVENZIP_PATH", str(executable))
    archive = make_archive(tmp_path / "archive.zip")
    target = tmp_path / "out" / "store.sqlite"
    assert script.main(["--archive", str(archive), "--output", str(target), "--min-year", "2012"]) == 0
    output = capsys.readouterr().out
    assert "store size" in output and "rows_scanned" in output
    connection = sqlite3.connect(target)
    try:
        assert connection.execute("SELECT MIN(year) FROM measurements").fetchone()[0] == 2015
        filters = connection.execute("SELECT value FROM provenance WHERE key = 'filters'").fetchone()[0]
        assert '"min_year": 2012' in filters
    finally:
        connection.close()
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(target))
    from oah.waterbase import store

    assert store.store_status().ready
