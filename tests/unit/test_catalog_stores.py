"""The located-site counts the catalogue reads from the stores, and the country name lookup. SYNTHETIC stores (tmp dirs)."""
from __future__ import annotations

from pathlib import Path

import pytest
from bathing_fixtures import HEADER, row
from bathing_fixtures import build_fixture_store as build_classification_store
from waterbase_fixtures import build_fixture_store as build_waterbase_store

from oah.bathing import service as bathing_service
from oah.bathing import store as bathing_store
from oah.indices.regimes import country_name
from oah.waterbase import service as waterbase_service
from oah.waterbase import store as waterbase_store


def test_waterbase_located_counts_split_rivers_and_lakes_and_skip_sites_without_coordinates(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(build_waterbase_store(tmp_path)))
    # IT: one river and one lake with coordinates, one river without; GR: its only site has none; NO: one river
    assert waterbase_store.located_counts() == {"IT": (1, 1), "NO": (1, 0)}
    assert waterbase_service.located_counts() == {"IT": (1, 1), "NO": (1, 0)}


def test_waterbase_located_counts_of_an_absent_store_are_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(tmp_path / "absent.sqlite"))
    assert waterbase_store.located_counts() == {} and waterbase_service.located_counts() == {}


def test_bathing_located_counts_skip_bathing_waters_without_coordinates(tmp_path: Path, monkeypatch):
    path = build_classification_store(
        tmp_path,
        rows=[
            HEADER,
            row("IT", "ITSYN001", 2022, "1 - Excellent"),
            row("IT", "ITSYN002", 2022, "2 - Good"),
            row("IT", "ITSYN003", 2022, "2 - Good", lon=None, lat=None),
            row("EL", "ELSYN001", 2023, "1 - Excellent", lon=None, lat=None),
        ],
    )
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(path))
    assert bathing_store.located_counts() == {"IT": 2}  # Greece has none with coordinates, so it is absent
    assert bathing_service.located_counts() == {"IT": 2}


def test_bathing_located_counts_of_an_absent_store_are_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(tmp_path / "absent.sqlite"))
    assert bathing_store.located_counts() == {} and bathing_service.located_counts() == {}


@pytest.mark.parametrize(("code", "name"), [("GR", "Greece"), ("IT", "Italy"), ("NO", "Norway"), ("DE", None), ("EL", None)])
def test_a_country_name_is_given_only_where_the_project_carries_one(code: str, name: str | None):
    assert country_name(code) == name
