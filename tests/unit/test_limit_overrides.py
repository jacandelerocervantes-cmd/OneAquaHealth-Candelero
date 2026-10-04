"""The limits file: changing values without editing code, safely and visibly."""

import copy
import json
from pathlib import Path

import pytest

from oah import config
from oah.indices import limit_overrides as lo
from oah.indices import regimes, water_parameter_limits
from oah.indices.apply_to_sandbox import apply_ccme_wqi_to_sandbox
from oah.indices.limit_verification import current_limits, verification_status
from oah.paths import REPO_ROOT

PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"
RIVER = [{"coding": [{"system": "http://snomed.info/sct", "code": "420531007"}]}]


@pytest.fixture(autouse=True)
def _restore():
    """Leave the shipped limits exactly as they were, whatever a test loads."""
    before = {name: copy.deepcopy(table) for name, table in lo._tables().items()}
    yield
    lo.reset_overrides()
    for name, table in lo._tables().items():
        table.clear()
        table.update(before[name])
    lo._ORIGINALS = None


def _doc(*limits, **extra):
    return {"schema_version": 1, "note": "test", "limits": list(limits), **extra}


def _limit(**fields):
    base = {"regime": "drinking", "country": None, "parameter": "Nitrate", "values": [45.0], "unit": "mg/L", "source": "test source"}
    base.update(fields)
    return base


def _obs(loc, code, value, unit="mg/L"):
    return {
        "id": f"o-{loc}-{code}",
        "meta": {"profile": [PROFILE]},
        "subject": {"reference": f"Location/{loc}"},
        "code": {"coding": [{"code": code}]},
        "valueQuantity": {"value": value, "unit": unit, "code": unit},
    }


def test_the_example_file_is_valid_and_changes_the_documented_limits():
    example = json.loads(Path(REPO_ROOT, "docs", "limits_override.example.json").read_text(encoding="utf-8"))
    report = lo.apply_overrides(example, "example")
    assert report.limits == 4 and report.locations == 2
    assert water_parameter_limits.CLOSED_PARAM_MAPPING["nitrate"][1] == 45.0
    assert water_parameter_limits.TWO_SIDED_LIMITS["pH"] == (6.0, 9.0)
    assert regimes.COUNTRY_SURFACE_LIMITS["XX"]["Nitrate"] == 8.0
    assert regimes.LOCATION_COUNTRY_OVERRIDES["Loc-Example-River"] == "XX"


def test_a_drinking_override_changes_the_score_and_is_labelled():
    obs = [_obs("L1", "nitrate", 47.0)]
    before = apply_ccme_wqi_to_sandbox(obs)["evaluated_locations"][0]
    assert before["ccme_wqi"] == 100.0  # 47 <= 50
    lo.apply_overrides(_doc(_limit()))
    result = apply_ccme_wqi_to_sandbox(obs)
    after = result["evaluated_locations"][0]
    assert after["ccme_wqi"] < 100.0  # 47 > 45
    assert after["limit_basis"]["Nitrate"].startswith("override: test source")
    assert after["limit_basis"]["Nitrate"].endswith("[unverified]")


def test_a_new_country_and_its_locations_can_be_added():
    lo.apply_overrides(_doc(
        _limit(regime="surface", country="XX", values=[8.0]),
        location_countries={"R1": "XX"}, location_regimes={"R1": "surface"},
    ))
    river = {"id": "R1", "type": RIVER, "description": ""}
    entry = apply_ccme_wqi_to_sandbox([_obs("R1", "nitrate", 9.0)], [river])["evaluated_locations"][0]
    assert entry["limit_country"] == "XX" and entry["limit_regime"] == "surface"
    assert entry["ccme_wqi"] < 100.0  # 9 > 8
    assert entry["limit_basis"]["Nitrate"].startswith("override: test source")


def test_overridden_limits_are_never_reported_as_verified(monkeypatch):
    from oah.indices import limit_verification as lv

    key = "drinking|-|Nitrate"
    monkeypatch.setattr(lv, "VERIFICATIONS", {key: lv.Verification("auditor-1", "2026-10-01", (50.0,), "mg/L", "primary text")})
    assert verification_status(key) == "verified"
    lo.apply_overrides(_doc(_limit()))
    assert verification_status(key) == "stale"  # the signed value (50) is no longer the value in force (45)
    assert current_limits()[key].values == (45.0,)


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        (_limit(unit="ug/L"), "unit"),
        (_limit(parameter="Unobtainium"), "unknown parameter"),
        (_limit(values=[-1.0]), "greater than zero"),
        (_limit(values=[float("nan")]), "greater than zero"),
        (_limit(values=[True]), "greater than zero"),
        (_limit(values=[]), "one or two"),
        (_limit(values=[1.0, 2.0, 3.0]), "one or two"),
        (_limit(values=[45.0, 50.0]), "one value"),
        (_limit(source=" "), "source is required"),
        (_limit(regime="marine"), "regime"),
        (_limit(regime="drinking", country="IT"), "no country"),
        (_limit(regime="surface", country="italy"), "two capital letters"),
        (_limit(regime="surface", country=None, values=[1.0, 2.0]), "only supported for drinking"),
        (_limit(parameter="pH", unit="pH", values=[9.0, 6.0]), "lower below upper"),
        (_limit(extra="x"), "only"),
    ],
)
def test_bad_entries_are_refused_with_a_clear_message(entry, message):
    with pytest.raises(lo.LimitOverrideError, match=message):
        lo.apply_overrides(_doc(entry))


@pytest.mark.parametrize(
    "document",
    [[], {"limits": []}, {"schema_version": 2}, {"schema_version": 1, "limits": "x"}, {"schema_version": 1, "unknown": 1},
     {"schema_version": 1, "location_countries": {"a": "italy"}}, {"schema_version": 1, "location_regimes": {"a": "sea"}}],
)
def test_bad_documents_are_refused(document):
    with pytest.raises(lo.LimitOverrideError):
        lo.apply_overrides(document)


def test_a_half_valid_file_changes_nothing():
    good, bad = _limit(values=[45.0]), _limit(parameter="Sulphate", values=[-5.0])
    with pytest.raises(lo.LimitOverrideError):
        lo.apply_overrides(_doc(good, bad))
    assert water_parameter_limits.CLOSED_PARAM_MAPPING["nitrate"][1] == 50.0
    assert regimes.OVERRIDE_SOURCES == {}


def test_loading_twice_does_not_stack_and_reset_restores_the_shipped_values():
    lo.apply_overrides(_doc(_limit(values=[40.0])))
    lo.apply_overrides(_doc(_limit(values=[45.0])))  # the second file replaces the first, it does not add to it
    assert water_parameter_limits.CLOSED_PARAM_MAPPING["nitrate"][1] == 45.0
    lo.reset_overrides()
    assert water_parameter_limits.CLOSED_PARAM_MAPPING["nitrate"][1] == 50.0
    assert regimes.OVERRIDE_SOURCES == {}


def test_a_lead_override_keeps_its_date_and_can_change_the_dated_value():
    lo.apply_overrides(_doc(_limit(parameter="Lead dissolved", unit="ug/L", values=[8.0, 4.0])))
    assert water_parameter_limits.CLOSED_PARAM_MAPPING["lead-dissolved"][1] == 8.0
    assert regimes.DATED_DRINKING_LIMITS["Lead dissolved"][1] == 4.0
    assert regimes.DATED_DRINKING_LIMITS["Lead dissolved"][0].year == 2036


def test_the_file_is_reread_when_it_changes_and_a_bad_edit_keeps_the_last_good_limits(tmp_path):
    path = tmp_path / "limits.json"
    path.write_text(json.dumps(_doc(_limit(values=[45.0]))), encoding="utf-8")
    assert lo.ensure_overrides_loaded(path).limits == 1
    assert water_parameter_limits.CLOSED_PARAM_MAPPING["nitrate"][1] == 45.0

    path.write_text(json.dumps(_doc(_limit(values=[42.0]))), encoding="utf-8")
    import os
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))
    lo.ensure_overrides_loaded(path)
    assert water_parameter_limits.CLOSED_PARAM_MAPPING["nitrate"][1] == 42.0  # edited while "running"

    path.write_text("{ not json", encoding="utf-8")
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 10))
    lo.ensure_overrides_loaded(path)  # not strict: keeps the last good state
    assert water_parameter_limits.CLOSED_PARAM_MAPPING["nitrate"][1] == 42.0
    with pytest.raises(lo.LimitOverrideError, match="OAH_LIMITS_FILE"):
        lo.ensure_overrides_loaded(path, strict=True)

    lo.ensure_overrides_loaded(None)  # unsetting the variable restores the shipped limits
    assert water_parameter_limits.CLOSED_PARAM_MAPPING["nitrate"][1] == 50.0


def test_the_pipeline_reads_the_configured_file_and_reports_it(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from oah.indices import apply_to_sandbox

    path = tmp_path / "limits.json"
    path.write_text(json.dumps(_doc(_limit(), note="hackathon demo")), encoding="utf-8")
    monkeypatch.setattr(apply_to_sandbox, "load_settings", lambda: SimpleNamespace(limits_file=path))
    result = apply_ccme_wqi_to_sandbox([_obs("L1", "nitrate", 47.0)])
    assert result["limit_overrides"] == {"file": "limits.json", "note": "hackathon demo", "limits": 1, "locations": 0}
    assert result["evaluated_locations"][0]["ccme_wqi"] < 100.0
    monkeypatch.setattr(apply_to_sandbox, "load_settings", lambda: SimpleNamespace(limits_file=None))
    restored = apply_ccme_wqi_to_sandbox([_obs("L1", "nitrate", 47.0)])
    assert restored["limit_overrides"] is None and restored["evaluated_locations"][0]["ccme_wqi"] == 100.0


def test_the_setting_must_be_an_absolute_path_or_unset():
    assert config.load_settings({}).limits_file is None
    with pytest.raises(RuntimeError, match="absolute"):
        config.load_settings({"OAH_LIMITS_FILE": "limits.json"})
