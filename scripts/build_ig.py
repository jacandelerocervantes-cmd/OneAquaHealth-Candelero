"""Build the extracted IG outside the repository with SUSHI."""
from __future__ import annotations
import os
import stat
import shutil
import subprocess
import sys
from oah.fhir.ig_build import find_sushi, load_resource_counts, sushi_totals
from oah.paths import ig_build_path, ig_path

def _clear_readonly_and_retry(function, path, _error) -> None:
    """Windows keeps the read-only attribute copied from source folders; clear it and retry."""
    os.chmod(path, stat.S_IWRITE)
    function(path)


def _remove_tree(path) -> None:
    # `onexc` exists from Python 3.12; `onerror` is the equivalent on the supported 3.11.
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_clear_readonly_and_retry)
    else:
        shutil.rmtree(path, onerror=_clear_readonly_and_retry)


def main() -> None:
    sushi = find_sushi()
    if not sushi:
        raise SystemExit("SUSHI is required; install it globally before building the IG.")
    build = ig_build_path()
    if not ig_path().is_dir():
        raise SystemExit("Extracted IG is missing; run oah-extract-ig first.")
    if build.exists():
        _remove_tree(build)
    shutil.copytree(ig_path(), build)
    result = subprocess.run([sushi, "."], cwd=build, text=True, capture_output=True)
    print(result.stdout)
    totals = sushi_totals(result.stdout + result.stderr)
    if totals is None:
        print("Warning: SUSHI totals could not be read.")
        errors = 0
    else:
        errors, warnings = totals
        print(f"SUSHI totals: {errors} Errors {warnings} Warnings")
    resources = build / "fsh-generated" / "resources"
    counts = load_resource_counts(resources) if resources.is_dir() else {}
    if result.returncode or errors or not counts.get("StructureDefinition"):
        raise SystemExit("SUSHI reported errors; see output above.")
    print(counts)

if __name__ == "__main__":
    main()
