"""Tests for read-only public-sandbox Observation classification."""

import pytest

from oah.ingest.classification import classify_observation


@pytest.mark.parametrize(
    "identifier",
    [
        "Obs-Almyros-sample",
        "Obs-Benevento01-sample",
        "Obs-BN-sample",
        "Obs-OS-sample",
        "Obs-WaterTemp-sample",
        "Obs-EC-sample",
    ],
)
def test_observed_official_prefixes_are_classified_as_official(identifier):
    assert classify_observation({"id": identifier}) == "official"


def test_other_or_missing_identifiers_are_classified_as_other():
    assert classify_observation({"id": "participant-test-data"}) == "other"
    assert classify_observation({}) == "other"
