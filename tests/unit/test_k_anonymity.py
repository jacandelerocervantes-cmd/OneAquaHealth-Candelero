"""Unit tests for k-anonymity enforcement."""

import pytest

from oah.privacy.k_anonymity import enforce_k_anonymity


def test_k_anonymity_satisfied():
    records = [
        {"age_group": "30-40", "zip": "1000", "score": 10},
        {"age_group": "30-40", "zip": "1000", "score": 12},
        {"age_group": "30-40", "zip": "1000", "score": 14},
        {"age_group": "50-60", "zip": "2000", "score": 20},
        {"age_group": "50-60", "zip": "2000", "score": 22},
        {"age_group": "50-60", "zip": "2000", "score": 25},
    ]
    result = enforce_k_anonymity(records, quasi_identifiers=["age_group", "zip"], k=3)
    assert len(result) == 6


def test_k_anonymity_violation_raises_error_with_violating_groups():
    records = [
        {"age_group": "30-40", "zip": "1000", "val": 1},
        {"age_group": "30-40", "zip": "1000", "val": 2},
        {"age_group": "50-60", "zip": "2000", "val": 3},
    ]
    with pytest.raises(ValueError) as exc_info:
        enforce_k_anonymity(records, quasi_identifiers=["age_group", "zip"], k=3)

    err_msg = str(exc_info.value)
    assert "k-anonymity (k=3) violated" in err_msg
    assert "count=2" in err_msg or "count=1" in err_msg


def test_k_anonymity_k_one_or_empty_records_returns_input():
    records = [{"zip": "1000"}]
    res1 = enforce_k_anonymity(records, quasi_identifiers=["zip"], k=1)
    assert res1 == records

    res_empty = enforce_k_anonymity([], quasi_identifiers=["zip"], k=5)
    assert res_empty == []


def test_k_anonymity_invalid_k_raises():
    with pytest.raises(ValueError):
        enforce_k_anonymity([{"a": 1}], quasi_identifiers=["a"], k=0)
