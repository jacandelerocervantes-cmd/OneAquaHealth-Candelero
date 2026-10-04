"""Stage the three prebuilt SQLite stores for the container image build.

The Waterbase and bathing-water stores are built by hand (7-Zip and a 4.5 GB archive; see docs/waterbase_store.md and
docs/bathing_water_store.md), the bathing-samples store by a two-minute download (docs/bathing_samples_store.md); all
live outside the repository. The production image ships them prebuilt. This script
checks the three stores and copies them, with a ``manifest.json``, into a staging directory OUTSIDE the repository
(default: ``deploy_stage`` under the data directory), which ``docker buildx build --build-context stores=<dir>``
then uses as an additional build context (docs/deployment.md).

It refuses to continue when a store is missing, unreadable, damaged or of another schema version than the code
reads. Nothing is written to the repository and no host path is written to the manifest.

Usage: ``python scripts/stage_deploy_stores.py`` (``--dry-run`` checks only, ``--output`` picks another absolute directory).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oah.bathing import store as bathing_store
from oah.bathing_samples import store as samples_store
from oah.paths import (
    BATHING_SAMPLES_STORE_NAME,
    BATHING_WATER_STORE_NAME,
    REPO_ROOT,
    WATERBASE_STORE_NAME,
    bathing_samples_store_path,
    bathing_water_store_path,
    deploy_stage_dir,
    external_path,
    waterbase_store_path,
)
from oah.timeutil import format_utc, utc_now
from oah.waterbase import store as waterbase_store

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
CONTAINER_STORE_DIR = "/data/stores"  # where the Dockerfile puts the files (and what OAH_*_STORE point at)
CHUNK_BYTES = 1024 * 1024


class StageError(Exception):
    """A store cannot be staged; the message says which one and why."""


@dataclass(frozen=True)
class StoreSpec:
    name: str
    file_name: str
    source: Path
    build_hint: str
    supported_schema: str
    status: Callable[[Path], Any]
    provenance: Callable[[Path], dict[str, str]]


@dataclass(frozen=True)
class StoreReport:
    spec: StoreSpec
    schema_version: str
    build_date_utc: str
    edition: str | None
    bytes: int
    sha256: str | None = None


def default_specs() -> list[StoreSpec]:
    """The three stores as the running configuration resolves them (``OAH_*_STORE`` or the data directory)."""
    return [
        StoreSpec(
            "waterbase", WATERBASE_STORE_NAME, waterbase_store_path(), "scripts/build_waterbase_store.py",
            waterbase_store.SUPPORTED_SCHEMA, waterbase_store.store_status, waterbase_store.provenance,
        ),
        StoreSpec(
            "bathing_water", BATHING_WATER_STORE_NAME, bathing_water_store_path(), "scripts/build_bathing_water_store.py",
            bathing_store.SUPPORTED_SCHEMA, bathing_store.store_status, bathing_store.provenance,
        ),
        StoreSpec(
            "bathing_samples", BATHING_SAMPLES_STORE_NAME, bathing_samples_store_path(), "scripts/build_bathing_samples_store.py",
            samples_store.SUPPORTED_SCHEMA, samples_store.store_status, samples_store.provenance,
        ),
    ]


def _quick_check(path: Path) -> bool:
    """SQLite's own structural check, on a read-only connection (False when it fails or the file cannot be opened)."""
    try:
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as connection:
            row = connection.execute("PRAGMA quick_check").fetchone()
    except (sqlite3.Error, OSError):
        return False
    return bool(row) and row[0] == "ok"


def inspect_store(spec: StoreSpec, path: Path | None = None) -> StoreReport:
    """Validate one store through its own module (state, schema version, provenance) or raise ``StageError``."""
    target = path if path is not None else spec.source
    if not target.is_file():
        raise StageError(f"{spec.name} store not found at {target}; build it with {spec.build_hint}.")
    status = spec.status(target)
    if status.state != "ready":
        raise StageError(f"{spec.name} store is {status.state}: {status.detail}")
    provenance = spec.provenance(target)
    schema = provenance.get("schema_version")
    if schema != spec.supported_schema:
        raise StageError(f"{spec.name} store has schema version {schema!r}; the code reads {spec.supported_schema!r}.")
    build_date = provenance.get("build_date_utc")
    if not build_date:
        raise StageError(f"{spec.name} store provenance has no build_date_utc; rebuild it with {spec.build_hint}.")
    if not _quick_check(target):
        raise StageError(f"{spec.name} store failed SQLite quick_check (damaged file); rebuild it with {spec.build_hint}.")
    return StoreReport(spec, schema, build_date, provenance.get("edition"), target.stat().st_size)


def _copy_with_hash(source: Path, destination: Path) -> tuple[int, str]:
    """Copy through a temporary name and rename, so the staging directory never holds a half-written store."""
    temporary = destination.with_name(destination.name + ".partial")
    digest = hashlib.sha256()
    size = 0
    try:
        with source.open("rb") as reader, temporary.open("wb") as writer:
            for chunk in iter(lambda: reader.read(CHUNK_BYTES), b""):
                digest.update(chunk)
                writer.write(chunk)
                size += len(chunk)
        if size != source.stat().st_size:
            raise StageError(f"{source.name} changed while it was being copied; run the script again.")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return size, digest.hexdigest()


def check_output_dir(output: Path, specs: list[StoreSpec]) -> None:
    """The staging directory must be absolute, outside the repository and not the folder of a source store."""
    if not output.is_absolute():
        raise StageError("The staging directory must be an absolute path.")
    resolved = output.resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise StageError("The staging directory must be outside the repository.")
    for spec in specs:
        if (resolved / spec.file_name) == spec.source.resolve():
            raise StageError(f"The staging directory holds the source {spec.name} store itself; choose another one.")


def stage(specs: list[StoreSpec], output: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Validate every store, then copy them and write the manifest; returns the manifest."""
    check_output_dir(output, specs)
    reports = [inspect_store(spec) for spec in specs]  # every store is checked before anything is written
    entries: list[dict[str, Any]] = []
    if not dry_run:
        output.mkdir(parents=True, exist_ok=True)
    for report in reports:
        spec = report.spec
        sha256: str | None = None
        size = report.bytes
        if not dry_run:
            destination = output / spec.file_name
            size, sha256 = _copy_with_hash(spec.source, destination)
            inspect_store(spec, destination)  # the staged copy must read exactly like the source
        entries.append(
            {
                "name": spec.name,
                "file": spec.file_name,
                "container_path": f"{CONTAINER_STORE_DIR}/{spec.file_name}",
                "bytes": size,
                "sha256": sha256,
                "schema_version": report.schema_version,
                "build_date_utc": report.build_date_utc,
                "edition": report.edition,
            }
        )
    manifest: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "generated_utc": format_utc(utc_now()),
        "stores": entries,
    }
    if not dry_run:
        temporary = output / (MANIFEST_NAME + ".partial")
        temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        os.replace(temporary, output / MANIFEST_NAME)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage the prebuilt stores for the container image build.")
    parser.add_argument("--output", help="absolute staging directory (default: deploy_stage under the data directory)")
    parser.add_argument("--dry-run", action="store_true", help="check every store and print the plan; copy nothing")
    args = parser.parse_args(argv)
    try:
        output = external_path(args.output, "--output") if args.output else deploy_stage_dir()
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    try:
        manifest = stage(default_specs(), output, dry_run=args.dry_run)
    except StageError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for entry in manifest["stores"]:
        print(f"{entry['name']}: {entry['file']} schema {entry['schema_version']} built {entry['build_date_utc']} {entry['bytes']} bytes")
    if args.dry_run:
        print(f"dry run: all stores are valid; nothing was copied (staging directory would be {output})")
    else:
        print(f"staged in {output}")
        print("next: docker buildx build --build-context stores=<that directory> ... (docs/deployment.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
