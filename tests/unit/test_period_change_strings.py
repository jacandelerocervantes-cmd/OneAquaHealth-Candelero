"""The two fixed strings added for the period comparison exist, in the final wording, in all 26 languages."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest
from waterbase_fixtures import NITRATE, build_fixture_store, obs

from oah.i18n.languages import LANGUAGES, SOURCE_LANGUAGE
from oah.i18n.strings import ENGLISH, all_strings, english_digest, validate_strings

KEYS = ("approximation_notice", "bathing_change_notice")


def test_the_final_english_wording_is_in_place_and_not_the_provisional_one():
    assert ENGLISH["approximation_notice"] == (
        "Screening aid, not a compliance assessment: each period is summarised by its mean, which is compared with "
        "the limit. National aggregation rules such as LIMeco or HWQI are not reproduced."
    )
    assert "Approximation:" not in ENGLISH["approximation_notice"] and "indicative" not in ENGLISH["approximation_notice"]
    assert len(ENGLISH["approximation_notice"]) < 200 and len(ENGLISH["interpretation_notice"]) < 200  # whole after the chat sanitiser
    assert "excellent, good, sufficient and poor" in ENGLISH["bathing_change_notice"] and "No concentration or threshold" in ENGLISH["bathing_change_notice"]
    assert not re.search(r"\d", ENGLISH["approximation_notice"] + ENGLISH["bathing_change_notice"])  # no number to keep in step


@pytest.mark.parametrize("code", [c for c in LANGUAGES if c != SOURCE_LANGUAGE])
def test_every_translation_carries_both_strings_machine_drafted_and_in_step_with_english(code):
    strings = all_strings()[code]
    assert strings.review_status == "machine-draft"
    for key in KEYS:
        text = strings.get(key)
        assert text and text != ENGLISH[key]
        assert text.strip() == text and len(text) <= 600
    assert "LIMeco" in strings.get("approximation_notice") and "HWQI" in strings.get("approximation_notice")  # names are not translated
    assert english_digest()  # the digest every file carries


def test_a_stale_translation_is_refused_by_the_existing_validation():
    data = {"language": "fr", "review_status": "machine-draft", "source_sha256": "0" * 64, "strings": {k: "x" for k in ENGLISH}}
    with pytest.raises(ValueError, match="stale"):
        validate_strings("fr", data)


def test_the_measurements_table_is_read_through_its_primary_key_not_scanned(tmp_path: Path):
    """No secondary index exists on measurements (it would double the file); the scope read must still be index driven."""
    path = build_fixture_store(tmp_path, rows=[obs(NITRATE, "1.0"), obs(NITRATE, "2.0", date="20210101")])
    connection = sqlite3.connect(path)
    try:
        indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='measurements'")}
        assert all(name.startswith("sqlite_autoindex") for name in indexes) or not indexes
        plan = " ".join(
            str(row)
            for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM measurements WHERE determinand = ? AND matrix = ? "
                "AND site_id IN (SELECT site_id FROM sites WHERE country = ?) AND (year * 12 + month - 1 BETWEEN ? AND ?)",
                [NITRATE[0], "W", "IT", 0, 10**6],
            )
        )
        assert "SEARCH measurements USING PRIMARY KEY" in plan and "SCAN measurements" not in plan
    finally:
        connection.close()
