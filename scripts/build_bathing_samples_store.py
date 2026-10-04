"""Build the EEA bathing-water SAMPLES SQLite store (E. coli and intestinal enterococci, Greece and Italy) from Discodata.

Usage::

    python scripts/build_bathing_samples_store.py [--output PATH] [--work-dir PATH] [--page-size N] [--max-pages N]
                                                  [--min-interval SECONDS] [--restart] [--keep-work] [--dry-run]

Reads the public, read-only EEA Discodata SQL service with keyset pages (no OFFSET, which the service refuses), politely
paced (default one request per 0.5 s) and with a descriptive User-Agent. Every downloaded page is saved in the work
directory, so an interrupted run resumes; the final store is written atomically. Defaults come from ``oah.paths`` (the
store under the data directory or at ``OAH_BATHING_SAMPLES_STORE``). ``--dry-run`` prints the resolved paths, the query
texts and the bounds and makes NO request. See ``docs/bathing_samples_store.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from oah.bathing_samples.build import ExtractionError, IncompleteExtraction, build_store, load_resume, query_texts
from oah.bathing_samples.client import DiscodataClient
from oah.bathing_samples.constants import (
    DEFAULT_PAGE_SIZE,
    ENDPOINT,
    HARD_MAX_PAGES,
    MAX_PAGE_SIZE,
    MIN_REQUEST_INTERVAL_SECONDS,
    PREFIX_TO_COUNTRY,
)
from oah.paths import bathing_samples_store_path, bathing_samples_work_dir, external_path


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("--output", help="absolute path of the SQLite store to write (default: OAH_BATHING_SAMPLES_STORE or the data directory)")
    parser.add_argument("--work-dir", help="absolute path of the directory that keeps the downloaded pages (default: under the data directory)")
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE, help=f"rows per request, 1 to {MAX_PAGE_SIZE} (default {DEFAULT_PAGE_SIZE})")
    parser.add_argument("--max-pages", type=int, default=None, help=f"stop after this many NEW pages per country (default: until the end, at most {HARD_MAX_PAGES}); no store is written when this stops the data early")
    parser.add_argument("--min-interval", type=float, default=MIN_REQUEST_INTERVAL_SECONDS, help="seconds between requests (default 0.5, about two per second)")
    parser.add_argument("--restart", action="store_true", help="delete the saved pages and start from the beginning")
    parser.add_argument("--keep-work", action="store_true", help="keep the downloaded pages after a successful build")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and stop; no request is made")
    args = parser.parse_args(argv)

    if not 1 <= args.page_size <= MAX_PAGE_SIZE:
        parser.error(f"--page-size must be from 1 to {MAX_PAGE_SIZE}")
    if args.max_pages is not None and args.max_pages < 1:
        parser.error("--max-pages must be at least 1")
    if args.min_interval < 0.25:
        parser.error("--min-interval must be at least 0.25 seconds (be polite to the public service)")

    output = external_path(args.output, "--output") if args.output else bathing_samples_store_path()
    work_dir = external_path(args.work_dir, "--work-dir") if args.work_dir else bathing_samples_work_dir()
    print(f"endpoint: {ENDPOINT} (read-only GET, keyset pages of {args.page_size} rows, one request per {args.min_interval} s)")
    print(f"store:    {output.name} ({'exists, will be replaced' if output.is_file() else 'new'})")
    print(f"work dir: {work_dir.name}")
    for prefix, text in query_texts(args.page_size).items():
        saved = load_resume(work_dir, prefix) if work_dir.is_dir() and not args.restart else None
        note = f"{saved.pages} saved page(s), {saved.rows} rows{', complete' if saved.complete else ''}" if saved else "nothing saved"
        print(f"  {prefix} -> {PREFIX_TO_COUNTRY[prefix]}: {note}\n      {text}")
    if args.dry_run:
        return 0

    client = DiscodataClient(min_interval=args.min_interval)
    started = time.monotonic()
    try:
        result = build_store(
            client, output, work_dir, page_size=args.page_size, max_pages=args.max_pages,
            restart=args.restart, keep_work=args.keep_work, progress=lambda message: print(message, flush=True),
        )
    except IncompleteExtraction as error:
        print(f"incomplete: {error}", file=sys.stderr)
        return 3
    except ExtractionError as error:
        print(f"extraction error: {error}", file=sys.stderr)
        return 2
    print(f"built in {time.monotonic() - started:.0f} s; store size {output.stat().st_size / 1e6:.1f} MB ({output.stat().st_size} bytes)")
    for key in sorted(result):
        if not isinstance(result[key], dict):
            print(f"  {key}: {result[key]}")
    for key in ("sizes", "rows_by_prefix", "rows_kept_by_country", "kind_counts", "status_counts", "sample_status_counts",
                "observation_status_counts", "dates", "fetch_stats"):
        print(f"  {key}: {json.dumps(result[key], sort_keys=True)}")
    for country, seasons in result["seasons"].items():
        print(f"  seasons {country}: {json.dumps(seasons)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
