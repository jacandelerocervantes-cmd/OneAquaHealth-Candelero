"""SYNTHETIC data shared by the period-comparison tests: a tiny monthly Waterbase slice and a few sandbox annual records.

Every value is invented for the tests (nothing is a measurement) and chosen so that each expected number can be checked by
hand. ``rows()`` goes to ``waterbase_fixtures.build_fixture_store``; ``OBSERVATIONS`` and ``LOCATIONS`` stand for the sandbox.
"""

from __future__ import annotations

from typing import Any

from waterbase_fixtures import AMMONIUM, NITRATE, OXYGEN, TOTAL_P, obs

TURBIDITY = ("EEA_3112-01-4", "Turbidity", "{NTU}")
S1, S2, S3, LAKE = "IT01-001025", "IT01-002000", "IT03-ONLY2021", "IT02-LAKE1"
PERIODS = "a_from=2021-01&a_to=2021-12&b_from=2023-01&b_to=2023-12"


def rows() -> list[list[str]]:
    rows: list[list[str]] = [
        # S1 nitrate, 2021: two samples in May (10, 20) and one in June (30): annual mean 20.0, monthly means 15.0 and 30.0
        obs(NITRATE, "10.0", site=S1, date="20210510"), obs(NITRATE, "20.0", site=S1, date="20210520"),
        obs(NITRATE, "30.0", site=S1, date="20210615"),
        # S1 nitrate, 2023: 40 in three months; and one value in December 2024 (the last month this site holds)
        obs(NITRATE, "40.0", site=S1, date="20230210"), obs(NITRATE, "40.0", site=S1, date="20230610"),
        obs(NITRATE, "40.0", site=S1, date="20231010"), obs(NITRATE, "60.0", site=S1, date="20241201"),
        # S1 total phosphorus (mg{P}/L): 0.04 in 2021 (limit 0.100 as P, within) and 0.12 in 2023 (exceeds), one below LOQ
        obs(TOTAL_P, "0.04", site=S1, date="20210310"), obs(TOTAL_P, "0.04", site=S1, date="20210410"),
        obs(TOTAL_P, "0.04", site=S1, date="20210510"),
        obs(TOTAL_P, "0.12", site=S1, date="20230310"), obs(TOTAL_P, "0.12", site=S1, date="20230510"),
        obs(TOTAL_P, "0.12", site=S1, date="20230710"), obs(TOTAL_P, "0.02", site=S1, date="20230810", below="1"),
        # S1 turbidity (measurement only): mean 6 in 2021, 12 in 2023
        obs(TURBIDITY, "4.0", site=S1, date="20210110"), obs(TURBIDITY, "6.0", site=S1, date="20210210"),
        obs(TURBIDITY, "8.0", site=S1, date="20210310"),
        obs(TURBIDITY, "12.0", site=S1, date="20230110"), obs(TURBIDITY, "12.0", site=S1, date="20230210"),
        obs(TURBIDITY, "12.0", site=S1, date="20230310"),
        # S2 nitrate: 5.0 in 2021, 7.0 in 2023 (a second river with enough data in both periods)
        *[obs(NITRATE, "5.0", site=S2, date=f"2021{month:02d}10") for month in (1, 2, 3)],
        *[obs(NITRATE, "7.0", site=S2, date=f"2023{month:02d}10") for month in (1, 2, 3)],
        # S3: data in 2021 only (never compared with a site that has both)
        *[obs(NITRATE, "99.0", site=S3, date=f"2021{month:02d}10") for month in (1, 2, 3)],
        # an Italian lake: no limit regime
        *[obs(NITRATE, "4.0", site=LAKE, category="LW", date=f"2021{month:02d}10") for month in (1, 2, 3)],
        *[obs(NITRATE, "6.0", site=LAKE, category="LW", date=f"2023{month:02d}10") for month in (1, 2, 3)],
        # Norway: nitrate reported as N (a basis the project refuses to convert)
        obs(NITRATE, "0.4", country="NO", site="NO0001", uom="mg{N}/L", date="20150312"),
        obs(NITRATE, "0.6", country="NO", site="NO0001", uom="mg{N}/L", date="20150601"),
        # Greece
        obs(OXYGEN, "5.0", country="EL", site="EL000123", date="20150312"),
        obs(AMMONIUM, "0.05", country="EL", site="EL000123", date="20150601"),
    ]
    return rows


PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"
RIVER = [{"coding": [{"system": "http://snomed.info/sct", "code": "420531007"}]}]
LOCATIONS = [
    {"resourceType": "Location", "id": "Loc-Almyros", "name": "Almyros", "type": RIVER, "position": {"latitude": 35.3, "longitude": 25.0}},
    {"resourceType": "Location", "id": "Loc-Tiber", "name": "Tiber", "type": RIVER, "description": "Tiber river, Italy",
     "position": {"latitude": 41.9, "longitude": 12.5}},
]


def _annual(obs_id: str, code: str, value: float, loc: str, start: str, end: str, comparator: str | None = None) -> dict[str, Any]:
    quantity: dict[str, Any] = {"value": value, "code": "mg/L", "system": "http://unitsofmeasure.org"}
    if comparator:
        quantity["comparator"] = comparator
    return {
        "id": obs_id, "resourceType": "Observation", "meta": {"profile": [PROFILE]},
        "subject": {"reference": f"Location/{loc}"}, "code": {"coding": [{"code": code}]},
        "effectivePeriod": {"start": start, "end": end},
        "component": [{"code": {"coding": [{"code": "median"}]}, "valueQuantity": quantity}],
    }


OBSERVATIONS = [
    _annual("a-18", "nitrate", 3.0, "Loc-Almyros", "2018-01-01", "2018-12-31"),
    _annual("a-19", "nitrate", 4.0, "Loc-Almyros", "2019-01-01", "2019-12-31"),
    _annual("a-20", "nitrate", 5.0, "Loc-Almyros", "2020-01-01", "2020-12-31"),
    _annual("a-21", "nitrate", 0.05, "Loc-Almyros", "2021-01-01", "2021-12-31", comparator="<"),  # below the quantification limit
    _annual("t-18", "nitrate", 2.0, "Loc-Tiber", "2018-01-01", "2018-12-31"),
    _annual("t-19", "nitrate", 2.5, "Loc-Tiber", "2019-01-01", "2019-12-31"),
]


