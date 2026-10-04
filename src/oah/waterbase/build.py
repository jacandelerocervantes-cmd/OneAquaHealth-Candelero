"""Build the Waterbase SQLite store from the EEA archive (``scripts/build_waterbase_store.py`` is the command line).

Streams the 28 GB disaggregated CSV once, keeps only the slice described in ``docs/waterbase_store.md`` (countries
GR/EL, IT and NO; categories RW and LW; matrices W and W-DIS; the determinands of ``oah.waterbase.mapping``; sampling
years from ``MIN_YEAR``) and aggregates it per (country, site, category, determinand, matrix, unit, year, MONTH) into
``n``, ``sum``, ``min``, ``max``, ``n_below_loq`` and ``n_lower_reliability`` (schema version 3). Keeping the sum
and the count makes every coarser mean exact (sum of sums over sum of counts); the annual view the reader still offers
is computed from the months. A streaming aggregation keeps no sample values, so the store has NO median.

Values reported as below the limit of quantification are only counted (``n_below_loq``): the number the file holds for
such a row is never used as a measurement. The write is atomic (temporary file, then rename) and deterministic: rows
are written in key order, so the same input gives the same tables (only the provenance build date differs).

Layout: ``aggregate`` (the disaggregated stream), ``spatial`` (the site table), ``storage`` (the SQLite write) and
``archive`` (the zip and 7-Zip access); this module keeps ``build_store``, which sequences them, and re-exports the names of
the former single module.
"""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from oah.timeutil import format_utc, utc_now
from oah.waterbase.aggregate import (  # noqa: F401  (re-exported: the former single module's public names)
    REQUIRED_COLUMNS,
    Aggregates,
    Key,
    aggregate_disaggregated,
)
from oah.waterbase.archive import (  # noqa: F401  (re-exported)
    _copy_member,
    _find_member,
    compute_sha256,
    read_sha256_sidecar,
    sevenzip_lines,
    zip_lines,
)
from oah.waterbase.mapping import (
    ATTRIBUTION,
    CATEGORIES,
    COUNTRY_CODES,
    DETERMINANDS,
    EDITION,
    KEPT_DETERMINAND_CODES,
    LICENCE,
    MATRICES,
    MIN_YEAR,
    MISSING_VALUE_STATUSES,
    SOURCE_LABEL,
    SOURCE_URL,
)
from oah.waterbase.spatial import SpatialSite, read_spatial  # noqa: F401  (re-exported)
from oah.waterbase.storage import DDL, INDEXES, write_store  # noqa: F401  (re-exported)

# Version 3 (2026-10-02, package 5): MONTHLY resolution (the key gains the month, the mean column becomes the sum so any
# coarser mean is exact) and the ``country_ranges`` table (first and last month with data per country). Version 2 added
# ``country_determinands`` and the measurement-only determinands. An older store is reported as ``rebuild-required`` by
# the reader and never read.
SCHEMA_VERSION = "3"
DISAGGREGATED_INNER = "WISE6_DisaggregatedData-csv.zip"
SPATIAL_INNER = "WISE6_SpatialObjects_DerivedData-csv.zip"


def build_store(
    archive: Path,
    target: Path,
    work_dir: Path,
    *,
    stream_factory: Callable[[Path], AbstractContextManager[Iterator[bytes]]],
    min_year: int = MIN_YEAR,
    compute_hash: bool = False,
    build_date: str | None = None,
) -> dict[str, Any]:
    """Build the store from the outer archive and return the row counters.

    The two inner archives are copied into a scratch directory under ``work_dir`` (about 1.6 GB for the real
    edition) and removed afterwards. ``stream_factory`` turns the inner disaggregated archive into the stream of
    its CSV lines: ``sevenzip_lines`` for the real file, ``zip_lines`` in tests.
    """
    if not archive.is_file():
        raise FileNotFoundError(f"Waterbase archive not found: {archive.name}. See docs/waterbase_store.md.")
    work_dir.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="build-", dir=work_dir))
    try:
        with zipfile.ZipFile(archive) as outer:
            spatial_zip = _copy_member(outer, SPATIAL_INNER, scratch)
            disaggregated_zip = _copy_member(outer, DISAGGREGATED_INNER, scratch)
        with zipfile.ZipFile(spatial_zip) as inner:
            with inner.open(inner.namelist()[0]) as stream:
                spatial = read_spatial(io.TextIOWrapper(stream, encoding="utf-8-sig", newline=""))
        with stream_factory(disaggregated_zip) as lines:
            aggregates, counters = aggregate_disaggregated(lines, min_year)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if not aggregates:
        raise RuntimeError("No row survived the filters; refusing to write an empty store.")
    published = read_sha256_sidecar(archive)
    if compute_hash:
        sha, sha_source = compute_sha256(archive), "computed"
    else:
        sha, sha_source = (published, "sidecar file") if published else ("not available", "none")
    provenance = {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE_LABEL,
        "source_url": SOURCE_URL,
        "edition": EDITION,
        "licence": LICENCE,
        "attribution": ATTRIBUTION,
        "archive_name": archive.name,
        "archive_bytes": str(archive.stat().st_size),
        "archive_sha256": sha,
        "archive_sha256_source": sha_source,
        "build_date_utc": build_date or format_utc(utc_now()),
        "filters": json.dumps(
            {
                "countries": sorted(COUNTRY_CODES),
                "water_body_categories": sorted(CATEGORIES),
                "matrices": sorted(MATRICES),
                "matrices_per_determinand": {
                    code: sorted(d.stored_matrices) for code, d in sorted(DETERMINANDS.items()) if d.stored_matrices != MATRICES
                },
                "determinand_codes": sorted(KEPT_DETERMINAND_CODES),
                "determinand_groups": {code: d.group for code, d in sorted(DETERMINANDS.items())},
                "min_year": min_year,
                "dropped_observation_statuses": sorted(MISSING_VALUE_STATUSES),
                "below_loq": "counted in n_below_loq, never used as a value",
                "aggregation": "n, sum, min, max per (country, site, category, determinand, matrix, unit, year, month); any coarser mean is sum / n; no median",
            },
            sort_keys=True,
        ),
    }
    write_store(target, aggregates, spatial, provenance, counters)
    return dict(counters)
