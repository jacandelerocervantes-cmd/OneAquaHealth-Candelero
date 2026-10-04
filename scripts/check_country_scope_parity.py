"""Check, on the REAL stores, that the SQL-aggregated country comparison equals the row-materialising path, and measure both.

Usage::

    python scripts/check_country_scope_parity.py                 # parity and time/Python-heap peak of every case
    python scripts/check_country_scope_parity.py --isolated      # also the peak process memory of each path (one child each)
    python scripts/check_country_scope_parity.py --case 0        # one case only

Reads the Waterbase store and the bathing-samples store at their configured locations (``oah.paths``); it never writes to
them and never uses the network. Without a store the cases of that store are skipped. Not part of the test suite (the real
stores are not in the repository); the property tests in ``tests/property/test_country_scope_parity.py`` cover random
SYNTHETIC stores. Exit code 0 when every compared case agrees exactly, 1 when one differs.

The row path (``country_change_rows``) is the code as it was before the SQL aggregation: it builds one Python object per
monthly row. ``--isolated`` runs each path in a fresh child process and reports its peak process memory (working set) after
the imports and at the end; the peak is a high-water mark, so a comparison that needs less than the imports did shows no increase.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import tracemalloc
from collections.abc import Callable
from typing import Any

from oah.indices.period_change import Period, parse_year_month
from oah.indices.scope_guard import GUARD

HALVES = ("2010-01", "2017-06", "2017-07", "2024-12")  # 15 years split in two periods of 90 months
GREEK = ("2012-01", "2016-12", "2017-01", "2021-12")
# (source, country, parameter, a_from, a_to, b_from, b_to)
CASES: list[tuple[str, str, str, str, str, str, str]] = [
    ("waterbase", "IT", "pH", *HALVES),  # the largest (country, determinand) of the real store: about 96,500 monthly rows
    ("waterbase", "IT", "Total phosphates", *HALVES),
    ("waterbase", "IT", "Nitrate", *HALVES),
    ("waterbase", "IT", "Total suspended solids", *HALVES),
    ("waterbase", "IT", "BOD5", *HALVES),
    ("waterbase", "IT", "Chloride", *HALVES),
    ("waterbase", "IT", "Lead dissolved", *HALVES),
    ("waterbase", "NO", "Total organic carbon (TOC)", *HALVES),
    ("waterbase", "GR", "Nitrate", *GREEK),
    ("samples", "IT", "bathing-samples", *HALVES),
    ("samples", "GR", "bathing-samples", *HALVES),
    ("samples", "IT", "bathing-samples", "2008-05", "2016-06", "2016-07", "2024-10"),  # the longest windows: the whole store
    ("samples", "GR", "bathing-samples", "2008-05", "2016-06", "2016-07", "2024-10"),
    ("samples", "IT", "bathing-samples", "2019-05", "2019-09", "2023-05", "2023-09"),  # one bathing season against another
    ("samples", "GR", "bathing-samples", "2019-05", "2019-09", "2023-05", "2023-09"),
    ("samples", "IT", "bathing-samples", "2015-01", "2020-12", "2018-01", "2024-12"),  # overlapping windows
    ("samples", "GR", "bathing-samples", "2022-01", "2024-12", "2010-01", "2013-12"),  # swapped order
]


def _periods(case: tuple[str, str, str, str, str, str, str]) -> tuple[Period, Period]:
    *_head, a_from, a_to, b_from, b_to = case
    return (
        Period(parse_year_month(a_from), parse_year_month(a_to)), Period(parse_year_month(b_from), parse_year_month(b_to))
    )


def _runner(case: tuple[str, str, str, str, str, str, str], mode: str) -> Callable[[], dict[str, Any]] | None:
    source, country, parameter = case[:3]
    period_a, period_b = _periods(case)
    GUARD.clear()
    if source == "waterbase":
        from oah.waterbase import change
        from oah.waterbase import store as waterbase_store

        if not waterbase_store.store_status().ready:
            return None
        series = change.resolve_series(parameter)
        if series is None:
            return None
        function = change.country_change if mode == "sql" else change.country_change_rows
        return lambda: function(country, series, period_a, period_b)
    from oah.bathing_samples import change as samples_change
    from oah.bathing_samples import store as samples_store

    if not samples_store.store_status().ready:
        return None
    sample_function = samples_change.country_change if mode == "sql" else samples_change.country_change_rows
    return lambda: sample_function(country, period_a, period_b)


def _peak_working_set() -> int:
    """Peak resident memory of this process in bytes (Windows: PeakWorkingSetSize; POSIX: ru_maxrss)."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        function = kernel32.K32GetProcessMemoryInfo
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        function.restype = wintypes.BOOL
        if not function(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return 0
        return int(counters.PeakWorkingSetSize)
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def _child(index: int, mode: str) -> int:
    run = _runner(CASES[index], mode)
    if run is None:
        print(json.dumps({"skipped": True}))
        return 0
    before = _peak_working_set()
    started = time.perf_counter()
    result = run()
    elapsed = time.perf_counter() - started
    after = _peak_working_set()
    print(json.dumps({
        "seconds": round(elapsed, 2), "peak_after_imports_mb": round(before / 1e6, 1), "peak_mb": round(after / 1e6, 1),
        "paired": _paired(result),
    }))
    return 0


def _paired(result: dict[str, Any]) -> Any:
    if "indicators" in result:
        return {name: item["n_sites_paired"] for name, item in result["indicators"].items()}
    return result["n_sites_paired"]


def _measure(run: Callable[[], dict[str, Any]], heap: bool = True) -> tuple[dict[str, Any], float, float]:
    """The result, the seconds (measured WITHOUT tracemalloc, which slows Python callbacks several times) and the Python-heap
    peak in MB (a second run under tracemalloc when ``heap`` is true; the result and the seconds are those of the first)."""
    GUARD.clear()
    started = time.perf_counter()
    result = run()
    elapsed = time.perf_counter() - started
    peak = 0.0
    if heap:
        GUARD.clear()
        tracemalloc.start()
        run()
        peak = tracemalloc.get_traced_memory()[1] / 1e6
        tracemalloc.stop()
    return result, elapsed, peak


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--case", type=int, help="index of one case")
    parser.add_argument("--isolated", action="store_true", help="also measure each path's peak process memory in a child")
    parser.add_argument("--isolated-only", action="store_true", help="only the child measurements (no in-process parity check and no tracemalloc)")
    parser.add_argument("--child", nargs=2, metavar=("CASE", "MODE"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        return _child(int(args.child[0]), args.child[1])
    failures = 0
    for index, case in enumerate(CASES):
        if args.case is not None and args.case != index:
            continue
        label = f"[{index}] {case[0]} {case[1]} {case[2]} A {case[3]}..{case[4]} B {case[5]}..{case[6]}"
        rows_run, sql_run = _runner(case, "rows"), _runner(case, "sql")
        if rows_run is None or sql_run is None:
            print(f"{label}: skipped (store not ready or unknown parameter)")
            continue
        if args.isolated_only:
            print(label)
        else:
            by_rows, rows_seconds, _no_heap = _measure(rows_run, heap=False)  # its heap: use --isolated (process peak)
            by_sql, sql_seconds, sql_peak = _measure(sql_run)
            same = by_rows == by_sql
            failures += not same
            detail = ""
            if "indicators" in by_sql:  # a samples case: the verdict of each indicator apart
                detail = " (" + ", ".join(
                    f"{name}: {'EQUAL' if by_rows['indicators'][name] == item else 'DIFFERENT'}" for name, item in by_sql["indicators"].items()
                ) + ")"
            print(
                f"{label}: {'EQUAL' if same else 'DIFFERENT'}{detail}  paired {_paired(by_sql)}  "
                f"rows {rows_seconds:.2f}s  sql {sql_seconds:.2f}s, Python heap peak {sql_peak:.1f} MB (tracemalloc, second run)"
            )
        if args.isolated or args.isolated_only:
            for mode in ("rows", "sql"):
                done = subprocess.run(
                    [sys.executable, __file__, "--child", str(index), mode], capture_output=True, text=True, check=False
                )
                print(f"      {mode}: {done.stdout.strip() or done.stderr.strip()[-200:]}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
