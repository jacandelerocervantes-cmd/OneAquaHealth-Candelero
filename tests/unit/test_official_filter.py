"""The official-record filter: demo, simulated and third-party Observations never reach a count or an index."""

import pytest

from oah.ingest.official import EXCLUSION_REASONS, classify_official_record, split_official

OAH = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"
HEALTH = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-health-measure-oah"


def _obs(profile=OAH, tags=(), code="nitrate", system=None, obs_id="o1"):
    coding = {"code": code, **({"system": system} if system else {})}
    meta = {"tag": [{"code": t} for t in tags]}
    if profile is not None:
        meta["profile"] = [profile]
    return {"id": obs_id, "meta": meta, "code": {"coding": [coding]}}


def test_an_oah_record_is_official():
    assert classify_official_record(_obs()) == (True, None)
    assert classify_official_record(_obs(profile=HEALTH)) == (True, None)
    assert classify_official_record(_obs(profile="observation-with-component-oah")) == (True, None)


@pytest.mark.parametrize("tag", ["simulated", "demo", "synthetic", "SIMULATED"])
def test_tagged_records_are_excluded_with_their_tag_as_the_reason(tag):
    keep, reason = classify_official_record(_obs(tags=[tag]))
    assert keep is False and reason == f"tag-{tag.lower()}"


@pytest.mark.parametrize(
    "observation",
    [
        _obs(profile="https://streampulse.example/StructureDefinition/forecast"),
        _obs(profile="https://example.org/StructureDefinition/sl-observation"),
        _obs(code="sl-reading"),
        _obs(system="https://streamsense.example/codes"),
    ],
)
def test_third_party_records_are_excluded(observation):
    assert classify_official_record(observation) == (False, "third-party")


def test_a_record_without_a_profile_or_with_a_foreign_profile_is_excluded():
    assert classify_official_record(_obs(profile=None)) == (False, "no-profile")
    assert classify_official_record(_obs(profile="http://example.org/StructureDefinition/other")) == (
        False,
        "non-oah-profile",
    )


def test_a_tag_wins_over_a_profile_problem():
    assert classify_official_record(_obs(profile=None, tags=["demo"])) == (False, "tag-demo")


def test_the_word_sl_inside_a_normal_code_is_not_third_party():
    assert classify_official_record(_obs(code="dissolved-oxygen-slow"))[0] is True


def test_split_counts_every_reason_and_keeps_only_official_records():
    batch = [_obs(obs_id="a"), _obs(tags=["demo"]), _obs(tags=["simulated"]), _obs(profile=None), _obs(code="sl-x")]
    official, excluded = split_official(batch)
    assert [o["id"] for o in official] == ["a"]
    assert set(excluded) == set(EXCLUSION_REASONS)
    assert excluded["tag-demo"] == excluded["tag-simulated"] == excluded["no-profile"] == excluded["third-party"] == 1
    assert sum(excluded.values()) == 4


def test_malformed_meta_does_not_crash():
    assert classify_official_record({"id": "x", "meta": "oops"}) == (False, "no-profile")
    assert classify_official_record({"id": "x", "meta": {"tag": ["bad"], "profile": [3]}}) == (False, "no-profile")
