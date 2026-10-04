"""Guard: evaluation reports must compute their figures, never carry hand-typed results.

Regression for the 2026-09-26 audit: ``eval_reliability.py`` printed a hand-written win-rate table
(two of its cells disagreed with the measured values) and declared seed sets it never used.
"""
import re

from oah.paths import repo_path


def _source(name: str) -> str:
    return repo_path("scripts", name).read_text(encoding="utf-8")


def test_declared_seed_sets_are_used_by_the_reliability_report():
    source = _source("eval_reliability.py")
    for name in ("HELD_OUT_SEEDS", "FRESH_SEEDS"):
        assert len(re.findall(rf"\b{name}\b", source)) >= 2, f"{name} is declared but never used"


def test_reliability_report_has_no_hand_typed_grid_rows():
    source = _source("eval_reliability.py")
    assert not re.search(r'"\|\s*\*\*\d+x\d+\*\*\s*\|', source), "grid rows must be generated from measurements"


def test_conformal_report_does_not_assert_coverage_it_did_not_check():
    assert "closely tracks or exceeds" not in _source("eval_conformal.py")
