"""Build the bathing-water SAMPLES SQLite store from the EEA Discodata service (``scripts/build_bathing_samples_store.py``).

Two stages, both restartable (``extract`` and ``storage`` hold the stages, ``normalise`` the row rules; this module
keeps ``build_store``, which sequences them, and re-exports the names of the former single module):

1. EXTRACTION. For each identifier prefix (EL = Greece, IT = Italy, NO = Norway, which has no row) the table is read in
   KEYSET pages (``oah.bathing_samples.client``) and every page is saved as one file in a work directory outside the
   project. An interrupted build resumes from the last valid page file; a page file that is damaged, of another query or
   out of sequence is discarded together with the later ones. The number of rows extracted must equal the service's own
   ``COUNT(*)`` for the prefix, or the build stops.
2. STORE. The saved pages are normalised (every drop counted, every status kept as written, every value given a KIND) and
   written to SQLite atomically (temporary file, then rename), rows in key order, so the same input gives the same
   tables (only the build date differs).

What is kept: the RAW samples (bathing water, sample date, season, both values and both statuses, the sample status, the
EEA observation status, and whether free-text remarks exist; the remarks text itself is not stored). Nothing is
aggregated and nothing is turned into a plain number silently: only status-free values (kind Q) and confirmed high
values (kind C) are concentrations; limit-of-detection numbers, missing placeholders (the service writes 0 for them) and
unrecognised statuses carry their own kind and never enter a statistic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from oah.bathing_samples.client import COUNT_QUERY_TEMPLATE, PAGE_QUERY_TEMPLATE, DiscodataClient
from oah.bathing_samples.constants import (
    ATTRIBUTION,
    DEFAULT_PAGE_SIZE,
    EDITION,
    ENDPOINT,
    KIND_NAMES,
    LICENCE,
    MAX_PAGE_SIZE,
    OBSERVED_PROXY,
    PREFIX_TO_COUNTRY,
    SOURCE_LABEL,
    SOURCE_URL,
    TABLE,
    UNIT,
    UNIT_STATEMENT,
)
from oah.bathing_samples.extract import (  # noqa: F401  (re-exported: the former single module's public names)
    WORK_FORMAT,
    ExtractionError,
    IncompleteExtraction,
    PrefixResult,
    Progress,
    ResumeState,
    clear_work_dir,
    extract_prefix,
    load_resume,
    template_digest,
)
from oah.bathing_samples.normalise import (  # noqa: F401  (re-exported)
    MAX_SEASON,
    MAX_STATUS_CHARS,
    MIN_SEASON,
    Sample,
    Tallies,
    classify_value,
    normalise_row,
)
from oah.bathing_samples.storage import DDL, INDEXES, RAW_DDL, _load_raw, write_store  # noqa: F401  (re-exported)
from oah.timeutil import format_utc, utc_now

SCHEMA_VERSION = "2"  # 2: covering and partial indexes for the country comparison (1: one index on country and date)


def query_texts(page_size: int) -> dict[str, str]:
    """The query text each prefix is read with (the keyset position is the placeholder ``<last UID>``)."""
    return {
        prefix: PAGE_QUERY_TEMPLATE.format(page_size=page_size, prefix=prefix, after_uid="<last UID>")
        for prefix in sorted(PREFIX_TO_COUNTRY)
    }


def build_store(
    client: DiscodataClient,
    target: Path,
    work_dir: Path,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int | None = None,
    restart: bool = False,
    keep_work: bool = False,
    build_date: str | None = None,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Extract (resuming) and write the store. Returns the counters and tallies (also kept in the provenance).

    ``max_pages`` bounds the pages fetched PER PREFIX in this run (a test and caution aid): when it stops the data early the
    work directory is kept and ``IncompleteExtraction`` is raised, and no store is written.
    """
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be from 1 to {MAX_PAGE_SIZE}")
    say: Progress = progress or (lambda _message: None)
    started_date = build_date or format_utc(utc_now())
    if restart:
        clear_work_dir(work_dir)
    results = [extract_prefix(client, work_dir, prefix, page_size, max_pages, say) for prefix in sorted(PREFIX_TO_COUNTRY)]
    incomplete = [item.prefix for item in results if not item.complete]
    if incomplete:
        raise IncompleteExtraction(
            f"the extraction stopped before the end for {incomplete} (max_pages); run again to resume from the saved pages"
        )
    mismatched = {item.prefix: (item.rows, item.source_count) for item in results if item.rows != item.source_count}
    if mismatched:
        raise ExtractionError(
            "extracted rows differ from the service's own count (prefix: (extracted, service count)): "
            f"{mismatched}; the work directory is kept, run with --restart for a clean attempt"
        )
    tallies = Tallies.new()
    raw_path = _load_raw(work_dir, results, tallies)
    counters = tallies.counters
    if counters["rows_kept"] == 0:
        raw_path.unlink(missing_ok=True)
        raise ExtractionError("no row survived the checks; refusing to write an empty store")
    rows_by_prefix = {item.prefix: item.rows for item in results}
    kept_by_country = {country: sum(counts.values()) for country, counts in sorted(tallies.seasons.items())}
    provenance = {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE_LABEL,
        "source_url": SOURCE_URL,
        "endpoint": ENDPOINT,
        "table": TABLE,
        "edition": EDITION,
        "latest_view_proxy_observed": OBSERVED_PROXY,
        "licence": LICENCE,
        "attribution": ATTRIBUTION,
        "build_date_utc": started_date,
        "complete": "true",
        "unit": UNIT,
        "unit_statement": UNIT_STATEMENT,
        "content": (
            "individual sample results (E. coli and intestinal enterococci); no classification, no threshold and no limit "
            "is in this store or applied by this project"
        ),
        "country_rule": "country = first two characters of bathingWaterIdentifier; EL (Greece) is stored as GR; NO has no row",
        "query_texts": json.dumps(query_texts(page_size), sort_keys=True),
        "count_query_text": COUNT_QUERY_TEMPLATE.format(prefix="<prefix>"),
        "page_size_requested": str(page_size),
        "rows_by_prefix_extracted": json.dumps(rows_by_prefix, sort_keys=True),
        "rows_by_prefix_service_count": json.dumps({i.prefix: i.source_count for i in results}, sort_keys=True),
        "rows_kept_by_country": json.dumps(kept_by_country, sort_keys=True),
        "rows_by_country_season": json.dumps(
            {country: {str(season): n for season, n in sorted(counts.items())} for country, counts in sorted(tallies.seasons.items())},
            sort_keys=True,
        ),
        "sample_date_range_by_country": json.dumps({c: v for c, v in sorted(tallies.dates.items())}, sort_keys=True),
        "value_kinds": json.dumps(KIND_NAMES, sort_keys=True),
        "kind_counts": json.dumps({name: dict(sorted(c.items())) for name, c in tallies.kinds.items()}, sort_keys=True),
        "status_counts": json.dumps({name: dict(sorted(c.items())) for name, c in tallies.statuses.items()}, sort_keys=True),
        "sample_status_counts": json.dumps(dict(sorted(tallies.sample_statuses.items())), sort_keys=True),
        "observation_status_counts": json.dumps(dict(sorted(tallies.observation_statuses.items())), sort_keys=True),
        "fetch_stats": json.dumps({**client.stats.as_dict(), "pages_per_prefix": {i.prefix: i.pages for i in results}}, sort_keys=True),
        "row_counts": json.dumps(dict(sorted(counters.items())), sort_keys=True),
    }
    try:
        sizes = write_store(target, raw_path, provenance)
    finally:
        raw_path.unlink(missing_ok=True)
    if not keep_work:
        clear_work_dir(work_dir)
    result: dict[str, Any] = dict(counters)
    result.update(
        sizes=sizes,
        rows_by_prefix=rows_by_prefix,
        rows_kept_by_country=kept_by_country,
        kind_counts={name: dict(c) for name, c in tallies.kinds.items()},
        status_counts={name: dict(c) for name, c in tallies.statuses.items()},
        sample_status_counts=dict(tallies.sample_statuses),
        observation_status_counts=dict(tallies.observation_statuses),
        seasons={c: dict(sorted(v.items())) for c, v in sorted(tallies.seasons.items())},
        dates={c: list(v) for c, v in sorted(tallies.dates.items())},
        fetch_stats=client.stats.as_dict(),
    )
    return result
