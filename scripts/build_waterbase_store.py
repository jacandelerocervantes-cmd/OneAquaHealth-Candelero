"""Build the EEA Waterbase SQLite store (rivers and lakes of GR/EL, IT and NO, annual aggregates).

Usage::

    python scripts/build_waterbase_store.py [--archive PATH] [--output PATH] [--min-year YEAR]
                                            [--compute-sha256] [--dry-run]

Defaults come from ``oah.paths`` (the archive under the data directory, the store under the data directory or at
``OAH_WATERBASE_STORE``). 7-Zip is located through ``OAH_SEVENZIP_PATH``, then ``7z`` on the PATH, then the standard
Windows install folder; it is needed because the 1.6 GB inner archive uses a compression method Python's zipfile cannot
read. The build copies the inner archives into a scratch directory under the data directory (about 1.7 GB, removed
afterwards). See ``docs/waterbase_store.md`` for the filters, the store layout and the limitations.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from oah.paths import external_path, sevenzip_executable, waterbase_archive_path, waterbase_store_path, waterbase_work_dir
from oah.waterbase.build import build_store, sevenzip_lines
from oah.waterbase.mapping import MIN_YEAR


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--archive", help="absolute path of the Waterbase outer ZIP (default: the data directory copy)")
    parser.add_argument("--output", help="absolute path of the SQLite store to write (default: OAH_WATERBASE_STORE or the data directory)")
    parser.add_argument("--min-year", type=int, default=MIN_YEAR, help=f"first sampling year kept (default {MIN_YEAR})")
    parser.add_argument("--compute-sha256", action="store_true", help="hash the archive (about a minute) instead of reading the .sha256 file")
    parser.add_argument("--dry-run", action="store_true", help="print the resolved paths and stop")
    args = parser.parse_args(argv)

    archive = external_path(args.archive, "--archive") if args.archive else waterbase_archive_path()
    output = external_path(args.output, "--output") if args.output else waterbase_store_path()
    sevenzip = sevenzip_executable()
    print(f"archive:  {archive.name} ({'found' if archive.is_file() else 'MISSING'})")
    print(f"store:    {output.name} ({'exists, will be replaced' if output.is_file() else 'new'})")
    print(f"7-Zip:    {sevenzip.name if sevenzip else 'NOT FOUND (set OAH_SEVENZIP_PATH or put 7z on the PATH)'}")
    print(f"min year: {args.min_year}")
    if args.dry_run:
        return 0
    if sevenzip is None:
        print("7-Zip is required to read the inner archive; install it or set OAH_SEVENZIP_PATH.", file=sys.stderr)
        return 2
    if not archive.is_file():
        print("The archive is missing; see docs/waterbase_store.md for where it must be.", file=sys.stderr)
        return 2

    started = time.monotonic()
    counters = build_store(
        archive,
        output,
        waterbase_work_dir(),
        stream_factory=lambda inner: sevenzip_lines(Path(sevenzip), inner),
        min_year=args.min_year,
        compute_hash=args.compute_sha256,
    )
    print(f"built in {time.monotonic() - started:.0f} s; store size {output.stat().st_size / 1e6:.1f} MB")
    for key in sorted(counters):
        print(f"  {key}: {counters[key]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
