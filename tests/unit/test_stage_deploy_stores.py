"""The store staging script for the container build. Stores are SYNTHETIC (built in tmp dirs by the real builders)."""

from __future__ import annotations

import hashlib
import importlib
import json
import sqlite3
import sys
from pathlib import Path
from types import ModuleType

import bathing_fixtures
import pytest
import samples_fixtures
import waterbase_fixtures

from oah.paths import BATHING_SAMPLES_STORE_NAME, BATHING_WATER_STORE_NAME, WATERBASE_STORE_NAME, repo_path


@pytest.fixture()
def script():
    scripts_dir = str(repo_path("scripts"))
    sys.path.insert(0, scripts_dir)
    try:
        yield importlib.import_module("stage_deploy_stores")
    finally:
        sys.path.remove(scripts_dir)
        sys.modules.pop("stage_deploy_stores", None)


@pytest.fixture()
def stores(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    """Synthetic stores under the exact file names the image expects, wired through the OAH_*_STORE variables."""
    water_dir = tmp_path / "w"
    bath_dir = tmp_path / "b"
    samples_dir = tmp_path / "s"
    water_dir.mkdir()
    bath_dir.mkdir()
    samples_dir.mkdir()
    water = waterbase_fixtures.build_fixture_store(water_dir, name=WATERBASE_STORE_NAME)
    bathing = bathing_fixtures.build_fixture_store(bath_dir, name=BATHING_WATER_STORE_NAME)
    samples = samples_fixtures.build_fixture_store(samples_dir, name=BATHING_SAMPLES_STORE_NAME)
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(water))
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(bathing))
    monkeypatch.setenv("OAH_BATHING_SAMPLES_STORE", str(samples))
    return water, bathing, samples


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_staging_copies_the_three_stores_and_writes_the_manifest(script: ModuleType, stores, tmp_path: Path):
    water, bathing, samples = stores
    output = tmp_path / "stage"
    manifest = script.stage(script.default_specs(), output)
    assert sorted(path.name for path in output.iterdir()) == sorted([WATERBASE_STORE_NAME, BATHING_WATER_STORE_NAME, BATHING_SAMPLES_STORE_NAME, "manifest.json"])
    on_disk = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk == manifest and on_disk["manifest_version"] == 1 and on_disk["generated_utc"]
    by_name = {entry["name"]: entry for entry in on_disk["stores"]}
    assert set(by_name) == {"waterbase", "bathing_water", "bathing_samples"}
    for key, source in (("waterbase", water), ("bathing_water", bathing), ("bathing_samples", samples)):
        entry = by_name[key]
        assert entry["file"] == source.name and entry["bytes"] == source.stat().st_size
        assert entry["sha256"] == _sha(source) == _sha(output / source.name)
        assert entry["container_path"] == f"/data/stores/{source.name}"
        assert entry["build_date_utc"] == ("2026-10-03T00:00:00Z" if key == "bathing_samples" else "2026-10-02T00:00:00Z")
    assert by_name["waterbase"]["schema_version"] == "3" and by_name["bathing_water"]["schema_version"] == "1"
    assert by_name["bathing_samples"]["schema_version"] == "2" and by_name["bathing_samples"]["edition"]
    assert by_name["bathing_samples"]["container_path"] == f"/data/stores/{BATHING_SAMPLES_STORE_NAME}"
    assert not any(str(tmp_path) in line for line in json.dumps(on_disk).splitlines()), "no host path in the manifest"


def test_the_container_paths_match_the_dockerfile_and_the_default_store_names(script: ModuleType):
    dockerfile = repo_path("Dockerfile").read_text(encoding="utf-8")
    for spec in script.default_specs():
        assert f"{script.CONTAINER_STORE_DIR}/{spec.file_name}" in dockerfile


def test_a_missing_store_is_refused_and_nothing_is_written(script: ModuleType, stores, tmp_path: Path):
    _, bathing, _ = stores
    bathing.unlink()
    output = tmp_path / "stage"
    with pytest.raises(script.StageError, match="bathing_water store not found.*build_bathing_water_store.py"):
        script.stage(script.default_specs(), output)
    assert not output.exists()


def test_a_wrong_schema_version_is_refused(script: ModuleType, stores, tmp_path: Path):
    water, _, _ = stores
    connection = sqlite3.connect(water)
    connection.execute("UPDATE provenance SET value = '99' WHERE key = 'schema_version'")
    connection.commit()
    connection.close()
    with pytest.raises(script.StageError, match="waterbase store is unreadable"):
        script.stage(script.default_specs(), tmp_path / "stage")
    assert not (tmp_path / "stage").exists()


def test_a_store_the_code_reads_at_another_schema_is_refused_by_the_version_check(script: ModuleType, stores, tmp_path: Path):
    specs = script.default_specs()
    other = type(specs[0])(**{**specs[0].__dict__, "supported_schema": "4"})
    with pytest.raises(script.StageError, match=r"schema version '3'; the code reads '4'"):
        script.stage([other, specs[1]], tmp_path / "stage")


def test_an_unreadable_file_is_refused(script: ModuleType, stores, tmp_path: Path):
    _, bathing, _ = stores
    bathing.write_bytes(b"this is not a sqlite database" * 40)
    with pytest.raises(script.StageError, match="bathing_water store is unreadable"):
        script.stage(script.default_specs(), tmp_path / "stage")


def test_a_damaged_but_openable_store_fails_the_quick_check(script: ModuleType, stores, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(script, "_quick_check", lambda path: False)
    with pytest.raises(script.StageError, match="quick_check"):
        script.stage(script.default_specs(), tmp_path / "stage")


def test_the_output_must_be_absolute_outside_the_repository_and_not_a_source_folder(script: ModuleType, stores, tmp_path: Path):
    water, _, _ = stores
    inside = repo_path("deploy_stage_must_not_exist")
    with pytest.raises(script.StageError, match="outside the repository"):
        script.stage(script.default_specs(), inside)
    with pytest.raises(script.StageError, match="outside the repository"):
        script.stage(script.default_specs(), repo_path("src"))
    assert not inside.exists()
    with pytest.raises(script.StageError, match="absolute"):
        script.stage(script.default_specs(), Path("relative") / "stage")
    with pytest.raises(script.StageError, match="source waterbase store itself"):
        script.stage(script.default_specs(), water.parent)


def test_a_rerun_is_idempotent_and_leaves_no_partial_files(script: ModuleType, stores, tmp_path: Path):
    output = tmp_path / "stage"
    first = script.stage(script.default_specs(), output)
    hashes = {path.name: _sha(path) for path in output.iterdir() if path.suffix == ".sqlite"}
    second = script.stage(script.default_specs(), output)
    assert {key: value for key, value in first.items() if key != "generated_utc"} == {
        key: value for key, value in second.items() if key != "generated_utc"
    }
    assert hashes == {path.name: _sha(path) for path in output.iterdir() if path.suffix == ".sqlite"}
    assert not [path for path in output.iterdir() if path.name.endswith(".partial")]


def test_a_dry_run_checks_but_copies_nothing(script: ModuleType, stores, tmp_path: Path, capsys):
    output = tmp_path / "stage"
    assert script.main(["--dry-run", "--output", str(output)]) == 0
    assert not output.exists()
    text = capsys.readouterr().out
    assert "dry run" in text and "schema 3" in text and "schema 1" in text and "bathing_samples:" in text


def test_a_missing_samples_store_is_refused_with_its_build_hint_and_nothing_is_written(script: ModuleType, stores, tmp_path: Path):
    stores[2].unlink()
    output = tmp_path / "stage"
    with pytest.raises(script.StageError, match="bathing_samples store not found.*build_bathing_samples_store.py"):
        script.stage(script.default_specs(), output)
    assert not output.exists()
    assert script.main(["--dry-run", "--output", str(output)]) == 1


@pytest.mark.parametrize("version", ["99", "1"])  # "1" is the store before the country-comparison indexes: it must be rebuilt
def test_a_samples_store_of_another_schema_version_is_refused(script: ModuleType, stores, tmp_path: Path, version: str):
    connection = sqlite3.connect(stores[2])
    connection.execute("UPDATE provenance SET value = ? WHERE key = 'schema_version'", (version,))
    connection.commit()
    connection.close()
    with pytest.raises(script.StageError, match="bathing_samples store is unreadable"):
        script.stage(script.default_specs(), tmp_path / "stage")
    assert not (tmp_path / "stage").exists()


def test_a_garbage_samples_file_is_refused_and_the_quick_check_applies_to_it(script: ModuleType, stores, tmp_path: Path, monkeypatch):
    original = script._quick_check
    seen: list[str] = []

    def recording(path: Path) -> bool:
        seen.append(path.name)
        return bool(original(path))

    monkeypatch.setattr(script, "_quick_check", recording)
    script.stage(script.default_specs(), tmp_path / "stage")
    assert BATHING_SAMPLES_STORE_NAME in seen
    stores[2].write_bytes(b"this is not a sqlite database" * 40)
    with pytest.raises(script.StageError, match="bathing_samples store is unreadable"):
        script.stage(script.default_specs(), tmp_path / "stage2")


def test_the_samples_store_must_not_be_staged_into_its_own_folder(script: ModuleType, stores):
    with pytest.raises(script.StageError, match="source bathing_samples store itself"):
        script.stage(script.default_specs(), stores[2].parent)


def test_the_command_line_reports_a_refusal_with_exit_code_1(script: ModuleType, stores, tmp_path: Path, capsys):
    stores[0].unlink()
    assert script.main(["--output", str(tmp_path / "stage")]) == 1
    assert "waterbase store not found" in capsys.readouterr().err
    assert script.main(["--output", "relative/stage"]) == 1
    assert "absolute" in capsys.readouterr().err


def test_the_command_line_stages_and_prints_the_next_step(script: ModuleType, stores, tmp_path: Path, capsys):
    output = tmp_path / "stage"
    assert script.main(["--output", str(output)]) == 0
    assert (output / "manifest.json").is_file()
    assert "staged in" in capsys.readouterr().out


def test_the_ci_synthetic_stores_build_and_stage_and_are_refused_inside_the_repository(script: ModuleType, tmp_path: Path, monkeypatch, capsys):
    scripts_dir = str(repo_path("scripts"))
    sys.path.insert(0, scripts_dir)
    try:
        synthetic = importlib.import_module("make_synthetic_stores")
    finally:
        sys.path.remove(scripts_dir)
        sys.modules.pop("make_synthetic_stores", None)
    water, bathing, samples = synthetic.build(tmp_path / "syn")
    assert water.name == WATERBASE_STORE_NAME and bathing.name == BATHING_WATER_STORE_NAME and samples.name == BATHING_SAMPLES_STORE_NAME
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(water))
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(bathing))
    monkeypatch.setenv("OAH_BATHING_SAMPLES_STORE", str(samples))
    manifest = script.stage(script.default_specs(), tmp_path / "stage")
    assert len(manifest["stores"]) == 3
    assert {entry["build_date_utc"] for entry in manifest["stores"]} == {"2000-01-01T00:00:00Z"}
    assert synthetic.main(["--output", str(repo_path("zz_must_not_exist"))]) == 1
    assert not repo_path("zz_must_not_exist").exists() and "outside the repository" in capsys.readouterr().err
