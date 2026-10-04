"""Privacy guard: no API response may carry person-level fields until ``oah.privacy`` is wired in.

``oah.privacy`` (k-anonymity, geo-generalisation, consent) is deliberately not applied to any endpoint
because no endpoint returns person-level data. This test keeps that true: adding a response field that
looks like a personal identifier or demographic attribute fails here, which is the signal to wire the
privacy module (and update this guard) BEFORE shipping the endpoint.
"""

from __future__ import annotations

import typing

from oah.api.app import app

PERSON_LEVEL_FIELD_NAMES = frozenset(
    {
        "patient", "patient_id", "person", "person_id", "individual", "birth_date", "birthdate", "dob",
        "age", "sex", "gender", "email", "phone", "telephone", "address", "ssn", "national_id",
        "first_name", "last_name", "full_name", "date_of_birth", "diagnosis", "medication",
    }
)


def _schemas() -> dict[str, dict[str, object]]:
    """Every schema of the API's OpenAPI document (routes included through routers are covered too)."""
    return app.openapi().get("components", {}).get("schemas", {})


def test_openapi_document_exposes_the_api_schemas():
    assert len(_schemas()) > 10  # the check really reaches the API's schemas


def test_no_response_field_is_a_person_level_identifier():
    offenders = sorted(
        f"{schema_name}.{field}"
        for schema_name, schema in _schemas().items()
        for field in typing.cast(dict[str, object], schema.get("properties", {}))
        if field.lower() in PERSON_LEVEL_FIELD_NAMES
    )
    assert offenders == [], f"person-level fields need oah.privacy wiring first: {offenders}"
