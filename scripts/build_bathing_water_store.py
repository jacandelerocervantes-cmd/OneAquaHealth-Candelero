"""Build the EEA bathing-water classification SQLite store (Greece, Italy, Norway; all seasons).

Usage::

    python scripts/build_bathing_water_store.py [--archive PATH] [--output PATH] [--dry-run]

Defaults come from ``oah.paths`` (the archive under the data directory, the store under the data directory or at
``OAH_BATHING_WATER_STORE``). The assessment sheet is streamed with the standard library (no third-party xlsx
package). The file holds the per-season CLASSIFICATION only, not E. coli or enterococci concentrations. See
``docs/bathing_water_store.md`` for the filters, the store layout and the limitations.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from oah.bathing.build import build_store
from oah.paths import bathing_water_archive_path, bathing_water_store_path, bathing_water_work_dir, external_path


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("--archive", help="absolute path of the bathing-water ZIP (default: the data directory copy)")
    parser.add_argument("--output", help="absolute path of the SQLite store to write (default: OAH_BATHING_WATER_STORE or the data directory)")
    parser.add_argument("--dry-run", action="store_true", help="print the resolved paths and stop")
    args = parser.parse_args(argv)

    archive = external_path(args.archive, "--archive") if args.archive else bathing_water_archive_path()
    output = external_path(args.output, "--output") if args.output else bathing_water_store_path()
    print(f"archive: {archive.name} ({'found' if archive.is_file() else 'MISSING'})")
    print(f"store:   {output.name} ({'exists, will be replaced' if output.is_file() else 'new'})")
    if args.dry_run:
        return 0
    if not archive.is_file():
        print("The archive is missing; see docs/bathing_water_store.md for where it must be.", file=sys.stderr)
        return 2

    started = time.monotonic()
    result = build_store(archive, output, bathing_water_work_dir())
    print(f"built in {time.monotonic() - started:.0f} s; store size {output.stat().st_size / 1e6:.1f} MB")
    for key in sorted(result):
        if key not in ("value_counts", "unknown_quality_values"):
            print(f"  {key}: {result[key]}")
    print(f"  unknown quality values: {result['unknown_quality_values'] or 'none'}")
    for name, counts in result["value_counts"].items():
        print(f"  {name}: {json.dumps(counts, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
