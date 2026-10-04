"""Synthetic test data only; no real sandbox records are used here."""
from copy import deepcopy
from hypothesis import given, strategies as st
from oah.qc.report import build_report

def observation(identifier, components, profile="profile"):
    return {"id": identifier, "meta": {"profile": [profile]} if profile else {}, "subject": {"reference": "Location/site"}, "component": components}

def component(code, value, unit="ug/L"):
    return {"code": {"coding": [{"code": code}]}, "valueQuantity": {"value": value, "system": "http://unitsofmeasure.org", "code": unit}}

def test_report_counts_and_does_not_mutate():
    data = [observation("clean", [component("minimum", 1), component("maximum", 2)]), observation("order", [component("minimum", 3), component("median", 2), component("maximum", 4)]), observation("mean", [component("minimum", 1), component("average", 4), component("maximum", 3)]), observation("ph", [component("minimum", 1, "pH")]), observation("none", [], None)]
    original = deepcopy(data)
    report = build_report(data, default_origin="real-sandbox")
    assert report["total_observations"] == 5
    assert report["findings"]["statistical-order"] == 1
    assert report["findings"]["mean-range"] == 1
    assert report["pH_code_to_review"] == 1
    assert "ucum-unit" not in report["findings"]
    assert report["observation_origin_counts"] == {"official": 0, "other": 5}
    assert data == original

@given(st.lists(st.booleans(), max_size=20))
def test_profile_counts_sum_to_total(flags):
    data = [observation(str(index), [], "a" if flag else None) for index, flag in enumerate(flags)]
    assert sum(build_report(data, default_origin="real-sandbox")["profiles"].values()) == len(data)


# --- Additional report contracts (synthetic test data only) ---------------------------------


def statistical_order_violation(identifier):
    return observation(
        identifier,
        [component("minimum", 3), component("median", 2), component("maximum", 4)],
    )


def test_examples_are_capped_at_twenty_but_total_is_complete():
    data = [statistical_order_violation(f"obs-{number}") for number in range(25)]
    report = build_report(data, default_origin="real-sandbox")
    entry = report["examples"]["statistical-order"]
    assert entry["total"] == 25
    assert len(entry["ids"]) == 20
    assert report["findings"]["statistical-order"] == 25


def test_air_and_conductivity_units_are_accepted_by_default():
    data = [
        observation(
            "air",
            [
                component("minimum", 1, "ug/m3"),
                component("median", 2, "ug/m3"),
                component("maximum", 3, "ug/m3"),
            ],
        ),
        observation(
            "conductivity",
            [
                component("minimum", 1, "uS/cm"),
                component("median", 2, "uS/cm"),
                component("maximum", 3, "uS/cm"),
            ],
        ),
    ]
    report = build_report(data, default_origin="real-sandbox")
    assert "ucum-unit" not in report["findings"]
    assert report["findings"] == {}


def test_ph_quantities_are_counted_for_review_not_as_unit_errors():
    data = [
        observation("ph-a", [component("minimum", 6, "pH"), component("maximum", 8, "pH")]),
        observation("ph-b", [component("minimum", 7, "pH")]),
    ]
    report = build_report(data, default_origin="real-sandbox")
    assert report["pH_code_to_review"] == 3
    assert report["findings_to_review"] == ["pH"]
    assert "ucum-unit" not in report["findings"]


def test_observation_origin_counts_use_only_observed_official_prefixes():
    data = [
        observation("Obs-Almyros-sample", []),
        observation("Obs-Benevento01-sample", []),
        observation("Obs-BN-sample", []),
        observation("Obs-OS-sample", []),
        observation("Obs-WaterTemp-sample", []),
        observation("Obs-EC-sample", []),
        observation("participant-test-data", []),
    ]
    assert build_report(data, default_origin="real-sandbox")["observation_origin_counts"] == {"official": 6, "other": 1}


def test_ucum_unit_examples_carry_real_observation_ids():
    data = [
        observation("bad-code", [component("minimum", 1, "furlong")]),
        observation("no-code", [{"code": {"coding": [{"code": "minimum"}]}, "valueQuantity": {"value": 1, "system": "http://unitsofmeasure.org"}}]),
    ]
    report = build_report(data, default_origin="real-sandbox")
    entry = report["examples"]["ucum-unit"]
    assert entry["total"] == 2
    assert sorted(entry["ids"]) == ["bad-code", "no-code"]
    assert all(identifier for identifier in entry["ids"])
    assert report["quantity_values_without_code"] == 1


class FakeClient:
    """Stands in for the sandbox client; no network."""

    def __init__(self, observations):
        self.observations = observations

    def pages(self, resource_type):
        assert resource_type == "Observation"
        yield self.observations


def test_cli_writes_only_under_the_configured_data_dir(monkeypatch, tmp_path, capsys):
    import json

    from oah.qc import cli

    data_dir = tmp_path / "data"
    working_dir = tmp_path / "cwd"
    working_dir.mkdir()
    monkeypatch.chdir(working_dir)
    observations = [statistical_order_violation("obs-1"), observation("clean", [])]
    monkeypatch.setattr(cli, "configured_client", lambda: FakeClient(observations))
    monkeypatch.setattr(cli, "qc_report_path", lambda name: data_dir / "reports" / name)

    cli.main()

    written = sorted(path.name for path in (data_dir / "reports").iterdir())
    assert written == ["observations.json", "observations.md"]
    report = json.loads((data_dir / "reports" / "observations.json").read_text(encoding="utf-8"))
    assert report["total_observations"] == 2
    markdown = (data_dir / "reports" / "observations.md").read_text(encoding="utf-8")
    assert "## Observation origin" in markdown
    assert "| other | 2 |" in markdown
    assert list(working_dir.iterdir()) == []
    printed = capsys.readouterr().out
    assert str(data_dir / "reports" / "observations.json") in printed
