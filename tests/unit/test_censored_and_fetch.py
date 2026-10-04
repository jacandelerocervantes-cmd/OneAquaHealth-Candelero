"""Censored-quantity handling and hardened sandbox fetching (synthetic inputs, no network)."""
import json
import os
import time

import httpx
import pytest

from oah.indices import sandbox_loader as mod
from oah.indices.apply_to_sandbox import apply_ccme_wqi_to_sandbox
from oah.indices.sandbox_loader import SandboxDataUnavailableError
from oah.indices.water_parameter_limits import classify_quantity, exact_numeric_value
from oah.qc.statistics import censored_quantities, component_statistics

PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-indicators-oah"


def _obs(oid, code, quantity, site="Location/S1"):
    return {
        "resourceType": "Observation",
        "id": oid,
        "meta": {"profile": [PROFILE]},
        "subject": {"reference": site},
        "code": {"coding": [{"code": code}]},
        "valueQuantity": quantity,
    }


def _q(value, **extra):
    return {"value": value, "system": "http://unitsofmeasure.org", "code": "mg/L", **extra}


@pytest.mark.parametrize(
    ("quantity", "expected"),
    [
        (_q(3), 3.0),
        (_q(2.5), 2.5),
        (_q(0.5, comparator="<"), None),
        (_q(0.5, comparator=">="), None),
        (_q(True), None),
        (_q("7"), None),
        ({}, None),
    ],
)
def test_exact_numeric_value(quantity, expected):
    assert exact_numeric_value(quantity) == expected


def test_censored_quantities_are_excluded_from_wqi_and_counted():
    exact = [_obs("a", "nitrate", _q(60.0)), _obs("b", "nitrate", _q(10.0)), _obs("c", "ammonium", _q(0.1))]
    baseline = apply_ccme_wqi_to_sandbox(exact)
    with_censored = apply_ccme_wqi_to_sandbox([*exact, _obs("d", "nitrate", _q(500.0, comparator=">"))])
    assert baseline["skipped_censored_quantities"] == 0
    assert with_censored["skipped_censored_quantities"] == 1
    assert with_censored["evaluated_locations"][0]["ccme_wqi"] == baseline["evaluated_locations"][0]["ccme_wqi"]
    assert with_censored["evaluated_locations"][0]["evaluable_measurements"] == 3


def test_site_with_only_indeterminate_censored_values_is_skipped_not_scored():
    result = apply_ccme_wqi_to_sandbox([_obs("a", "nitrate", _q(500.0, comparator=">"))])
    assert result["evaluated_locations_count"] == 0 and result["skipped_locations_count"] == 1
    assert result["skipped_censored_quantities"] == 1


def test_qc_flags_censored_value_and_component_quantities():
    observation = {
        "id": "o1",
        "valueQuantity": _q(1, comparator="<"),
        "component": [{"valueQuantity": _q(2)}, {"valueQuantity": _q(3, comparator=">")}],
    }
    findings = censored_quantities(observation)
    assert [f.path for f in findings] == ["valueQuantity", "component[1].valueQuantity"]
    assert all(f.code == "censored-quantity" and f.severity == "warning" and f.resource_id == "o1" for f in findings)
    assert [f.code for f in component_statistics(observation, {"mg/L"})] == ["censored-quantity"] * 2


def test_qc_reports_nothing_for_exact_quantities():
    assert censored_quantities({"id": "o", "valueQuantity": _q(1), "component": [{"valueQuantity": _q(2)}]}) == []


class _Client:
    def __init__(self, resources=None, error=None):
        self.resources, self.error = resources or [], error

    def pages(self, resource_type):
        if self.error:
            raise self.error
        yield self.resources


def _patch(monkeypatch, tmp_path, snapshot_text=None, client=None):
    snapshot = tmp_path / "Observation.json"
    if snapshot_text is not None:
        snapshot.write_text(snapshot_text, encoding="utf-8")
    monkeypatch.setattr(mod, "sandbox_snapshot_path", lambda resource_type: snapshot)
    monkeypatch.setattr(mod, "configured_client", lambda: client or _Client())


def test_valid_snapshot_is_used_without_touching_the_network(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, json.dumps([{"id": "s"}]), _Client(error=AssertionError("network used")))
    assert mod.fetch_sandbox_observations() == [{"id": "s"}]


@pytest.mark.parametrize("text", ["{not json", json.dumps({"id": "not-a-list"})])
def test_bad_snapshot_is_logged_and_live_sandbox_is_used(monkeypatch, tmp_path, caplog, text):
    _patch(monkeypatch, tmp_path, text, _Client([{"id": "live"}]))
    assert mod.fetch_sandbox_observations() == [{"id": "live"}]
    assert "Ignoring" in caplog.text


def test_live_failure_raises_instead_of_returning_an_empty_real_sandbox_list(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, None, _Client(error=httpx.ConnectError("down")))
    with pytest.raises(SandboxDataUnavailableError, match="Observation"):
        mod.fetch_sandbox_observations()


def test_unexpected_programming_errors_are_not_swallowed(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, None, _Client(error=KeyError("bug")))
    with pytest.raises(KeyError):
        mod.fetch_sandbox_observations()


def test_locations_use_the_same_loader(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, None, _Client([{"id": "L1"}]))
    assert mod.fetch_sandbox_locations() == [{"id": "L1"}]


def _age(path, seconds):
    then = time.time() - seconds
    os.utime(path, (then, then))


def test_stale_snapshot_is_skipped_in_favour_of_the_live_sandbox(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, json.dumps([{"id": "old"}]), _Client([{"id": "live"}]))
    _age(tmp_path / "Observation.json", 3 * 24 * 3600)
    assert mod.fetch_sandbox_observations() == [{"id": "live"}]


def test_stale_snapshot_is_used_offline_with_a_warning(monkeypatch, tmp_path, caplog):
    _patch(monkeypatch, tmp_path, json.dumps([{"id": "old"}]), _Client(error=httpx.ConnectError("down")))
    _age(tmp_path / "Observation.json", 3 * 24 * 3600)
    assert mod.fetch_sandbox_observations() == [{"id": "old"}]
    assert "72.0-hour-old" in caplog.text


@pytest.mark.parametrize(
    ("comparator", "bound", "limit", "is_lower", "expected"),
    [
        ("<", 0.5, 10.0, False, ("pass-by-bound", 0.5)),   # non-detect below the limit passes
        ("<=", 10.0, 10.0, False, ("pass-by-bound", 10.0)),
        ("<", 20.0, 10.0, False, ("indeterminate", None)),  # detection limit above the limit
        (">", 20.0, 10.0, False, ("indeterminate", None)),  # would fail, amplitude unknown
        (">=", 8.0, 6.0, True, ("pass-by-bound", 8.0)),     # lower-limit parameter (dissolved oxygen)
        (">", 4.0, 6.0, True, ("indeterminate", None)),
        ("<", 2.0, 6.0, True, ("indeterminate", None)),     # certainly fails, amplitude unknown
    ],
)
def test_classify_quantity_uses_only_what_the_bound_proves(comparator, bound, limit, is_lower, expected):
    assert classify_quantity(_q(bound, comparator=comparator), limit, is_lower) == expected


def test_classify_quantity_exact_and_invalid():
    assert classify_quantity(_q(3), 10.0, False) == ("exact", 3.0)
    assert classify_quantity({"comparator": "<"}, 10.0, False) == ("invalid", None)
    assert classify_quantity(_q(True, comparator="<"), 10.0, False) == ("invalid", None)


def test_non_detects_below_the_limit_count_as_passes_and_change_the_score_exactly():
    base = [_obs("a", "nitrate", _q(60.0)), _obs("b", "ammonium", _q(0.1))]
    nondetects = [_obs("c", "nitrate", _q(5.0, comparator="<")), _obs("d", "ammonium", _q(0.05, comparator="<"))]
    as_exact = [_obs("c", "nitrate", _q(5.0)), _obs("d", "ammonium", _q(0.05))]
    result = apply_ccme_wqi_to_sandbox(base + nondetects)
    assert result["censored_quantities_counted_as_pass"] == 2
    assert result["skipped_censored_quantities"] == 0
    # a passing exact value at the bound gives the identical score: excursion is 0 either way
    assert result["evaluated_locations"][0]["ccme_wqi"] == apply_ccme_wqi_to_sandbox(base + as_exact)["evaluated_locations"][0]["ccme_wqi"]
    assert result["evaluated_locations"][0]["evaluable_measurements"] == 4
