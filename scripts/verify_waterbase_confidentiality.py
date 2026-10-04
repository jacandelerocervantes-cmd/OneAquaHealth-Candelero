"""Read-only check that no restricted Waterbase site has coordinates in the built store.

Usage::

    python scripts/verify_waterbase_confidentiality.py [--store PATH]

Reads the ``sites`` table of the store (default: ``oah.paths.waterbase_store_path``, which honours ``OAH_WATERBASE_STORE``)
through a read-only connection and asserts the privacy rule of ``docs/waterbase_store.md``: a site whose confidentiality
status is not ``F`` (free for publication) has NULL ``lat`` and ``lon``. Prints the counts per country and status.
Exit code 0 when the rule holds, 1 when a restricted site has coordinates, 2 when the store cannot be read. It never
writes to the store.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys

from oah.paths import external_path, waterbase_store_path
from oah.waterbase.mapping import FREE_FOR_PUBLICATION

_FREE = f"COALESCE(TRIM(confidentiality) = '{FREE_FOR_PUBLICATION}', 0)"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--store", help="absolute path of the SQLite store (default: OAH_WATERBASE_STORE or the data directory)")
    args = parser.parse_args(argv)
    target = external_path(args.store, "--store") if args.store else waterbase_store_path()
    if not target.is_file():
        print(f"store: {target.name} is missing; build it with scripts/build_waterbase_store.py")
        return 2
    try:
        connection = sqlite3.connect(f"{target.resolve().as_uri()}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only=ON")
        rows = connection.execute(
            f"SELECT country, {_FREE} AS free, COALESCE(TRIM(confidentiality), '(blank)'), COUNT(*), "
            "SUM(lat IS NOT NULL OR lon IS NOT NULL) FROM sites GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"
        ).fetchall()
        connection.close()
    except sqlite3.Error as error:
        print(f"store: cannot be read ({type(error).__name__}); is it a Waterbase store?")
        return 2
    leaking = 0
    print(f"store: {target.name}")
    for country, free, status, sites, with_coordinates in rows:
        with_coordinates = int(with_coordinates or 0)
        verdict = "free for publication" if free else "RESTRICTED"
        print(f"  {country}  status {status:<8} {verdict:<22} sites {sites:>6}  with coordinates {with_coordinates:>6}")
        if not free:
            leaking += with_coordinates
    if leaking:
        print(f"FAIL: {leaking} restricted site(s) have coordinates in the store")
        return 1
    restricted = sum(int(sites) for _c, free, _s, sites, _w in rows if not free)
    print(f"OK: {restricted} restricted site(s), none with coordinates")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
