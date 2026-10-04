"""Time the country comparison of bathing-water SAMPLES through the real API route, on the REAL samples store.

Usage::

    python scripts/measure_samples_country_route.py [--repeat N]

Read-only and offline: the store is the configured one (``oah.paths``), the access key is a throwaway generated here for this
process only, the external providers and the sandbox warm-up are switched off, and nothing is written. The request goes through
FastAPI's ``TestClient``, so the number includes the key check, the rate limit, the process-wide scope guard and the response
model. The first call of each case is a cold read (the guard's result cache is cleared); the second shows the cache. Not part of
the test suite (the real store is not in the repository). Exit code 0, or 2 when the store is not built.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import time

CASES = [  # (label, query string)
    ("IT halves 2010-01..2017-06 / 2017-07..2024-12", "country=IT&a_from=2010-01&a_to=2017-06&b_from=2017-07&b_to=2024-12"),
    ("IT longest 2008-05..2016-06 / 2016-07..2024-10", "country=IT&a_from=2008-05&a_to=2016-06&b_from=2016-07&b_to=2024-10"),
    ("IT seasons 2019 / 2023", "country=IT&a_from=2019-05&a_to=2019-09&b_from=2023-05&b_to=2023-09"),
    ("GR halves 2010-01..2017-06 / 2017-07..2024-12", "country=GR&a_from=2010-01&a_to=2017-06&b_from=2017-07&b_to=2024-12"),
    ("GR longest 2008-05..2016-06 / 2016-07..2024-10", "country=EL&a_from=2008-05&a_to=2016-06&b_from=2016-07&b_to=2024-10"),
]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--repeat", type=int, default=2, help="calls per case (the first is cold, the others come from the cache)")
    args = parser.parse_args(argv)
    key = secrets.token_urlsafe(32)  # throwaway: lives in this process only
    os.environ["OAH_API_KEY"] = key
    os.environ.pop("OAH_INSECURE_NO_AUTH", None)
    os.environ["OAH_EXTERNAL_ENABLED"] = "0"
    os.environ["OAH_SANDBOX_WARMUP"] = "0"

    from fastapi.testclient import TestClient

    from oah.api.app import app
    from oah.bathing_samples import store
    from oah.indices.scope_guard import GUARD

    if not store.store_status().ready:
        print("the samples store is not built (scripts/build_bathing_samples_store.py)")
        return 2
    client = TestClient(app)
    worst = 0.0
    for label, query in CASES:
        GUARD.clear()
        timings = []
        for _call in range(max(1, args.repeat)):
            started = time.perf_counter()
            response = client.get(f"/bathing-waters/samples/change?{query}", headers={"X-API-Key": key})
            timings.append((time.perf_counter() - started, response.status_code))
        worst = max(worst, timings[0][0])
        calls = ", ".join(f"{seconds:.2f}s (HTTP {status})" for seconds, status in timings)
        print(f"{label}: cold then cached: {calls}")
    print(f"slowest cold call: {worst:.2f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
