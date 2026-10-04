"""The limit-verification registry: every applied limit is listed, signatures bind to values, and stay honest."""

import re
from datetime import date

import pytest

from oah.indices import limit_verification as lv
from oah.indices.apply_to_sandbox import apply_ccme_wqi_to_sandbox
from oah.indices.regimes import COUNTRY_SURFACE_LIMITS, DRINKING, SURFACE, SURFACE_LIMITS
from oah.indices.water_parameter_limits import CLOSED_PARAM_MAPPING, TWO_SIDED_LIMITS
from oah.timeutil import utc_now

PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"


def test_every_limit_the_code_can_apply_has_a_key():
    records = lv.current_limits()
    for name, _limit, _ in CLOSED_PARAM_MAPPING.values():
        assert lv.limit_key(DRINKING, None, name) in records
    for name in SURFACE_LIMITS:
        assert lv.limit_key(SURFACE, None, name) in records
    for country, table in COUNTRY_SURFACE_LIMITS.items():
        for name in table:
            assert lv.limit_key(SURFACE, country, name) in records
    assert records["drinking|-|pH"].values == TWO_SIDED_LIMITS["pH"]
    assert records["drinking|-|Lead dissolved"].values == (10.0, 5.0)  # the limit and its dated replacement
    assert records["surface|IT|Dissolved oxygen saturation deviation"].values == (20.0,)


def test_the_committed_signatures_are_well_formed_and_match_their_limits():
    records = lv.current_limits()
    for key, signature in lv.VERIFICATIONS.items():
        assert key in records, f"signature for an unknown limit: {key}"
        assert re.fullmatch(r"[A-Za-z0-9._-]{2,64}", signature.verified_by), "a handle, not an e-mail address or a name"
        assert date.fromisoformat(signature.verified_on) <= utc_now().date()
        assert signature.evidence.strip()
        assert lv.verification_status(key) == "verified", f"{key} was signed for a different value or unit"


def test_no_agent_signed_anything_yet_so_every_limit_reads_unverified():
    assert lv.VERIFICATIONS == {}
    assert {lv.verification_status(key) for key in lv.current_limits()} == {"unverified"}


def _sign(monkeypatch, key, **overrides):
    record = lv.current_limits()[key]
    fields = {"verified_by": "auditor-1", "verified_on": "2026-10-01", "values": record.values, "unit": record.unit, "evidence": "primary provision"}
    fields.update(overrides)
    monkeypatch.setattr(lv, "VERIFICATIONS", {key: lv.Verification(**fields)})


def test_a_signature_is_verified_only_while_the_value_and_unit_match(monkeypatch):
    key = "drinking|-|Nitrate"
    _sign(monkeypatch, key)
    assert lv.verification_status(key) == "verified"
    assert lv.verification_label(DRINKING, None, "Nitrate") == "[verified by auditor-1 on 2026-10-01]"
    _sign(monkeypatch, key, values=(45.0,))  # signed for another number: stale, never silently trusted
    assert lv.verification_status(key) == "stale"
    _sign(monkeypatch, key, unit="ug/L")
    assert lv.verification_status(key) == "stale"
    assert "stale" in lv.verification_label(DRINKING, None, "Nitrate")


def test_a_signature_for_a_removed_limit_is_stale(monkeypatch):
    monkeypatch.setattr(lv, "VERIFICATIONS", {"drinking|-|Unobtainium": lv.Verification("auditor-1", "2026-10-01", (1.0,), "mg/L", "x")})
    assert lv.verification_status("drinking|-|Unobtainium") == "stale"


def test_every_output_states_the_verification_of_each_limit_it_used():
    observation = {
        "id": "o1",
        "meta": {"profile": [PROFILE]},
        "subject": {"reference": "Location/L1"},
        "code": {"coding": [{"code": "nitrate"}]},
        "valueQuantity": {"value": 1.0, "unit": "mg/L", "code": "mg/L"},
    }
    entry = apply_ccme_wqi_to_sandbox([observation])["evaluated_locations"][0]
    assert entry["limit_basis"]["Nitrate"].endswith("[unverified]")
    assert entry["limit_basis"]["Nitrate"].startswith("legal: Directive (EU) 2020/2184")


@pytest.mark.parametrize("values", [(1.0,), (1.0, 2.0)])
def test_value_comparison_is_length_and_tolerance_aware(values):
    assert lv._same(values, tuple(v + 1e-13 for v in values))
    assert not lv._same(values, values + (3.0,))
