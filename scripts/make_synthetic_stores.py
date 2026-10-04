"""Build three tiny SYNTHETIC stores under the production file names (CI image-build check only).

The container build needs the three prebuilt stores as an additional build context. Continuous integration has
neither the multi-gigabyte Eurostat archives nor any real data, so this script builds minimal stores with the real
builders (``oah.waterbase.build``, ``oah.bathing.build`` and ``oah.bathing_samples.build``) from the invented archives
and scripted fake service of the unit-test fixtures.
They contain invented data (build date 2000-01-01) and must never be deployed: they only prove that the image
builds and starts. Usage::

    python scripts/make_synthetic_stores.py --output <absolute empty directory>

then ``OAH_WATERBASE_STORE``, ``OAH_BATHING_WATER_STORE`` and ``OAH_BATHING_SAMPLES_STORE`` point at the printed files and
``scripts/stage_deploy_stores.py --output <stage dir>`` writes the staged context with its manifest.
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

from oah.bathing_samples.build import build_store as build_samples_store
from oah.paths import BATHING_SAMPLES_STORE_NAME, BATHING_WATER_STORE_NAME, WATERBASE_STORE_NAME, external_path, repo_path

SYNTHETIC_BUILD_DATE = "2000-01-01T00:00:00Z"


def build(output: Path) -> list[Path]:
    """Build the three synthetic stores in ``output`` (created if needed) and return their paths."""
    fixtures_dir = str(repo_path("tests", "unit"))
    sys.path.insert(0, fixtures_dir)
    try:
        water_fixtures = importlib.import_module("waterbase_fixtures")
        bathing_fixtures = importlib.import_module("bathing_fixtures")
        samples_fixtures = importlib.import_module("samples_fixtures")
    finally:
        sys.path.remove(fixtures_dir)
    water_dir = output / "work_waterbase"
    bathing_dir = output / "work_bathing"
    water_dir.mkdir(parents=True, exist_ok=True)
    bathing_dir.mkdir(parents=True, exist_ok=True)
    samples_dir = output / "work_samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    water = water_fixtures.build_fixture_store(water_dir, name=WATERBASE_STORE_NAME, build_date=SYNTHETIC_BUILD_DATE)
    bathing = bathing_fixtures.build_fixture_store(bathing_dir, name=BATHING_WATER_STORE_NAME, build_date=SYNTHETIC_BUILD_DATE)
    # The samples fixture helper pins its own build date, so the real builder is called directly with the invented
    # rows and the scripted fake service (no network) to give this store the same synthetic date as the others.
    samples = samples_dir / BATHING_SAMPLES_STORE_NAME
    service = samples_fixtures.FakeDiscodata(samples_fixtures.dataset())
    build_samples_store(
        samples_fixtures.make_client(service), samples, samples_dir / "work", page_size=5, build_date=SYNTHETIC_BUILD_DATE
    )
    return [Path(water), Path(bathing), samples]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build tiny synthetic stores for the CI image-build check.")
    parser.add_argument("--output", required=True, help="absolute directory outside the repository")
    args = parser.parse_args(argv)
    try:
        output = external_path(args.output, "--output")
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    resolved = output.resolve()
    if resolved == repo_path() or repo_path() in resolved.parents:
        print("error: --output must be outside the repository.", file=sys.stderr)
        return 1
    for path in build(output):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
