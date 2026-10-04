"""GBIF species context: request shape, filters, per-record licence and citation passthrough, counts, graceful failures."""
from __future__ import annotations

from datetime import date

import httpx
import pytest
from external_fakes import (
    GBIF_DATASET,
    GBIF_DATASET_2,
    GBIF_PUBLISHER,
    dataset_payload,
    gbif_handler,
    json_response,
    make_runtime,
    occurrence,
    search_payload,
)

from oah.external import constants as c
from oah.external import coords, gbif
from oah.external.envelope import ExternalInputError
from oah.external.gbif import licence_label, parse_record, species_context
from oah.external.settings import ExternalSettings
from oah.external.sites import LocatedSite
from oah.external.taxa import load_catalogue

SITE = LocatedSite("ITRIVER1", "PO - TEST", "waterbase-site", "real-eea-waterbase", "IT", 45.07, 7.69, "river")


def gbif_runtime(search=None, dataset=None, **kwargs):
    runtime, router, clock = make_runtime(**kwargs)
    router.on(c.GBIF_HOST, gbif_handler(search or (lambda request: json_response(search_payload([occurrence(1), occurrence(2)]))), dataset))
    return runtime, router, clock


def search_requests(router):
    return [r for r in router.requests if r.url.path == "/v1/occurrence/search"]


def test_search_request_shape_defaults_to_every_group() -> None:
    runtime, router, _ = gbif_runtime()
    species_context(runtime, SITE, None, None, None)
    request = search_requests(router)[0]
    query = request.url.params
    assert request.url.host == c.GBIF_HOST and request.method == "GET"
    assert query["geometry"] == coords.search_wkt(45.07, 7.69)
    assert sorted(query.get_list("taxonKey")) == sorted(str(g.usage_key) for g in load_catalogue().groups)
    assert query["occurrenceStatus"] == "PRESENT" and query["hasCoordinate"] == "true" and query["hasGeospatialIssue"] == "false"
    assert query["limit"] == "50" and query["offset"] == "0" and "eventDate" not in query
    assert query.get_list("facet") == ["orderKey", "familyKey"]


def test_records_keep_licence_dataset_publisher_citation_and_drop_the_observer() -> None:
    runtime, router, _ = gbif_runtime()
    result = species_context(runtime, SITE, None, None, None)
    assert result["status"] == "ok" and result["origin"] == "external-gbif" and result["data_kind"] == "opportunistic-occurrence-records"
    assert result["total_records"] == 2 and result["returned"] == 2
    record = result["records"][0]
    assert record["licence"] == "CC-BY-NC-4.0" and record["non_commercial_only"] is True and record["licence_text"] is None
    assert record["dataset_key"] == GBIF_DATASET and record["publishing_organization_key"] == GBIF_PUBLISHER
    assert record["dataset_name"] == "iNaturalist research-grade observations" and record["institution_code"] == "iNaturalist"
    assert "rights_holder" not in record and "an observer" not in repr(result)  # an individual's name is never passed on
    assert record["basis_of_record"] == "HUMAN_OBSERVATION" and record["event_date"] == "2026-05-01T10:47:34" and record["year"] == 2026
    assert record["coordinate_uncertainty_m"] == 37.0 and record["latitude"] == 45.0931 and record["longitude"] == 7.7255
    assert record["distance_km"] == pytest.approx(coords.distance_km(45.07, 7.69, 45.0931, 7.7255), abs=0.01)
    assert record["group"] == "trichoptera" and record["scientific_name"].startswith("Mystacides azureus")
    assert record["record_url"] is None  # a link on a third-party host (here inaturalist.org) is dropped
    assert record["coordinate_issues"] == ["COORDINATE_ROUNDED"]  # only coordinate issues are passed on
    assert record["citation"] == "iNaturalist contributors (2026). Test citation."
    assert result["datasets"] == [{"dataset_key": GBIF_DATASET, "title": "iNaturalist Research-grade Observations",
                                   "citation": "iNaturalist contributors (2026). Test citation.", "licence": "CC-BY-NC-4.0"}]
    assert "Observer Name" not in repr(result)  # recordedBy is never passed on
    assert result["licence_summary"] == {"CC-BY-NC-4.0": 2} and "non-commercial-licence-records" in result["flags"]
    assert sum(1 for r in router.requests if r.url.path.startswith("/v1/dataset/")) == 1  # one call per distinct dataset


@pytest.mark.parametrize(
    "raw, label",
    [
        ("http://creativecommons.org/publicdomain/zero/1.0/legalcode", "CC0-1.0"),
        ("https://creativecommons.org/publicdomain/zero/1.0/", "CC0-1.0"),
        ("CC0_1_0", "CC0-1.0"),
        ("http://creativecommons.org/licenses/by/4.0/legalcode", "CC-BY-4.0"),
        ("CC_BY_4_0", "CC-BY-4.0"),
        ("http://creativecommons.org/licenses/by-nc/4.0/legalcode", "CC-BY-NC-4.0"),
        ("CC_BY_NC_4_0", "CC-BY-NC-4.0"),
        ("http://creativecommons.org/licenses/by/3.0/", "other-or-unspecified"),
        ("All rights reserved", "other-or-unspecified"),
        ("", "other-or-unspecified"),
        (None, "other-or-unspecified"),
        (12, "other-or-unspecified"),
    ],
)
def test_licence_label(raw: object, label: str) -> None:
    assert licence_label(raw) == label


def test_an_unknown_licence_is_shown_as_given_and_never_hidden() -> None:
    runtime, _, _ = gbif_runtime(lambda request: json_response(search_payload([occurrence(1, license="http://example.org/odd-licence")])))
    record = species_context(runtime, SITE, None, None, None)["records"][0]
    assert record["licence"] == "other-or-unspecified" and record["licence_text"] == "http://example.org/odd-licence"
    assert record["non_commercial_only"] is False


def test_cc0_and_cc_by_records_carry_no_non_commercial_flag() -> None:
    records = [occurrence(1, license="http://creativecommons.org/publicdomain/zero/1.0/legalcode"),
               occurrence(2, license="http://creativecommons.org/licenses/by/4.0/legalcode")]
    runtime, _, _ = gbif_runtime(lambda request: json_response(search_payload(records)))
    result = species_context(runtime, SITE, None, None, None)
    assert result["licence_summary"] == {"CC0-1.0": 1, "CC-BY-4.0": 1} and "non-commercial-licence-records" not in result["flags"]


def test_group_filters_aliases_and_unknown_groups() -> None:
    runtime, router, _ = gbif_runtime()
    species_context(runtime, SITE, "ept", None, None)
    assert sorted(search_requests(router)[-1].url.params.get_list("taxonKey")) == ["1003", "1225", "787"]
    result = species_context(runtime, SITE, "Odonata", None, None)
    assert search_requests(router)[-1].url.params.get_list("taxonKey") == ["789"]
    assert result["filters"]["group"] == "odonata" and result["filters"]["groups_searched"] == ["odonata"]
    with pytest.raises(ExternalInputError, match="Unknown group"):
        species_context(runtime, SITE, "birds", None, None)


def test_date_filters_use_gbif_range_syntax() -> None:
    runtime, router, _ = gbif_runtime()
    for date_from, date_to, expected in [
        (date(2015, 1, 1), date(2020, 12, 31), "2015-01-01,2020-12-31"),
        (date(2024, 1, 1), None, "2024-01-01,*"),
        (None, date(2020, 12, 31), "*,2020-12-31"),
    ]:
        species_context(runtime, SITE, None, date_from, date_to)
        assert search_requests(router)[-1].url.params["eventDate"] == expected
    with pytest.raises(ExternalInputError):
        species_context(runtime, SITE, None, date(2020, 1, 2), date(2020, 1, 1))
    with pytest.raises(ExternalInputError):
        species_context(runtime, SITE, None, date(1500, 1, 1), None)


@pytest.mark.parametrize("limit", [0, -1, 201, True, "5", 2.5, None])
def test_limit_must_be_an_integer_from_1_to_200(limit: object) -> None:
    runtime, router, _ = gbif_runtime()
    with pytest.raises(ExternalInputError, match="limit"):
        species_context(runtime, SITE, None, None, None, limit)  # type: ignore[arg-type]
    assert router.requests == []


def test_limit_is_sent_and_200_is_accepted() -> None:
    runtime, router, _ = gbif_runtime()
    species_context(runtime, SITE, None, None, None, 200)
    assert search_requests(router)[0].url.params["limit"] == "200"


def test_counts_per_group_come_from_the_facets_and_missing_ones_are_zero() -> None:
    facets = [
        {"field": "ORDER_KEY", "counts": [{"name": "1003", "count": 4}, {"name": "1225", "count": 1}]},
        {"field": "FAMILY_KEY", "counts": [{"name": "3343", "count": 7}]},
        "bad", {"field": 5, "counts": []}, {"field": "ORDER_KEY", "counts": [{"name": 5, "count": 1}, "x", {"name": "787", "count": "many"}]},
    ]
    runtime, _, _ = gbif_runtime(lambda request: json_response(search_payload([occurrence(1)], count=12, facets=facets)))
    result = species_context(runtime, SITE, None, None, None)
    counts = {item["group"]: item["count"] for item in result["group_counts"]}
    assert counts == {"ephemeroptera": 1, "plecoptera": 0, "trichoptera": 4, "odonata": 0, "chironomidae": 7, "gammaridae": 0, "unionida": 0}
    assert all(item["caveat"] and item["rank"] in ("ORDER", "FAMILY") for item in result["group_counts"])
    assert result["total_records"] == 12 and result["returned"] == 1 and "truncated" in result["flags"]


def test_no_records_is_no_data_with_zero_counts() -> None:
    runtime, router, _ = gbif_runtime(lambda request: json_response(search_payload([], facets=[])))
    result = species_context(runtime, SITE, None, None, None)
    assert result["status"] == "no-data" and result["total_records"] == 0 and result["records"] == [] and result["datasets"] == []
    assert all(item["count"] == 0 for item in result["group_counts"])
    assert all(r.url.path == "/v1/occurrence/search" for r in router.requests)


def test_unusable_records_are_skipped_and_counted() -> None:
    items = [occurrence(1), "text", {"key": 2}, occurrence(3, decimalLatitude=95.0), occurrence(4, scientificName="  "),
             occurrence(5, decimalLongitude="x"), occurrence(True), occurrence(-4), occurrence(6, decimalLatitude=float("nan"))]
    runtime, _, _ = gbif_runtime(lambda request: json_response(search_payload(items, count=9)))
    result = species_context(runtime, SITE, None, None, None, 50)
    assert result["returned"] == 1 and result["n_records_skipped"] == 8


def test_text_fields_are_cleaned_and_bounded() -> None:
    record = parse_record(
        occurrence(1, scientificName="Evil <script>alert(1)</script>\x00 name" + "x" * 500, datasetName="a‮b", institutionCode="I" * 200,
                   references="javascript:alert(1)", basisOfRecord="human observation", datasetKey="not-a-uuid", year=99999,
                   publishingOrgKey=7, issues="COORDINATE_ROUNDED", rightsHolder=5),
        (45.07, 7.69), load_catalogue(),
    )
    assert record is not None
    assert "<" not in record["scientific_name"] and "\x00" not in record["scientific_name"] and len(record["scientific_name"]) <= 200
    assert record["dataset_name"] == "ab" and len(record["institution_code"]) == 60
    assert record["record_url"] is None and record["basis_of_record"] is None and record["dataset_key"] is None
    assert record["year"] is None and record["publishing_organization_key"] is None and record["coordinate_issues"] == []
    assert "rights_holder" not in record


@pytest.mark.parametrize(
    "url, kept",
    [
        ("https://www.gbif.org/occurrence/1", True),
        ("https://gbif.org/occurrence/1", True),
        ("https://api.gbif.org/v1/occurrence/1", True),
        ("https://www.gbif.org:443/occurrence/1", True),
        ("http://www.gbif.org/occurrence/1", False),  # plain http
        ("https://www.inaturalist.org/observations/357121084", False),  # another host
        ("https://gbif.org.evil.example/occurrence/1", False),  # look-alike suffix
        ("https://evilgbif.org/occurrence/1", False),  # look-alike prefix
        ("https://user:secret@www.gbif.org/occurrence/1", False),  # credentials
        ("https://www.gbif.org:8443/occurrence/1", False),  # unusual port
        ("https://www.gbif.org:notaport/occurrence/1", False),
        ("https://[::1/occurrence/1", False),  # malformed host
        ("ftp://www.gbif.org/occurrence/1", False),
        ("javascript:alert(1)", False),
        ("https://www.gbif.org/a b", False),
        ("", False),
        (None, False),
        (5, False),
    ],
)
def test_the_record_link_is_kept_only_for_https_on_gbif_org(url, kept) -> None:
    record = parse_record(occurrence(1, references=url), (45.07, 7.69), load_catalogue())
    assert record is not None
    assert record["record_url"] == (url if kept else None)


def test_rights_holder_and_recorded_by_never_reach_the_result_but_dataset_attribution_does() -> None:
    record = parse_record(
        occurrence(1, rightsHolder="Jane Q. Observer", recordedBy="jane_q", references="https://www.gbif.org/occurrence/1"),
        (45.07, 7.69), load_catalogue(),
    )
    assert record is not None
    text = repr(record)
    assert "Jane" not in text and "jane_q" not in text
    for kept in ("dataset_key", "dataset_name", "publishing_organization_key", "institution_code", "licence"):
        assert record[kept] is not None, kept
    assert record["record_url"] == "https://www.gbif.org/occurrence/1"


def test_a_record_of_a_family_group_is_assigned_to_it() -> None:
    record = parse_record(occurrence(1, order_key=811, family_key=3343, scientificName="Chironomus plumosus"), (45.07, 7.69), load_catalogue())
    assert record is not None and record["group"] == "chironomidae"
    other = parse_record(occurrence(2, order_key=1, family_key=2), (45.07, 7.69), load_catalogue())
    assert other is not None and other["group"] is None
    assert parse_record("x", (1.0, 1.0), load_catalogue()) is None


def test_dataset_citations_are_cached_for_a_day_and_shared_across_searches() -> None:
    runtime, router, clock = gbif_runtime()
    species_context(runtime, SITE, None, None, None)
    species_context(runtime, SITE, "ept", None, None)  # a different search, the same dataset
    dataset_calls = [r for r in router.requests if r.url.path.startswith("/v1/dataset/")]
    assert len(dataset_calls) == 1 and dataset_calls[0].url.path == f"/v1/dataset/{GBIF_DATASET}"
    clock.advance(24 * 3600 + 1)
    species_context(runtime, SITE, "odonata", None, None)
    assert len([r for r in router.requests if r.url.path.startswith("/v1/dataset/")]) == 2


def test_a_missing_citation_or_dataset_failure_is_graceful() -> None:
    records = [occurrence(1), occurrence(2, datasetKey=GBIF_DATASET_2)]

    def search(request):
        return json_response(search_payload(records))

    def dataset(key):
        return dataset_payload(citation=None)

    runtime, _, _ = gbif_runtime(search, dataset)
    result = species_context(runtime, SITE, None, None, None)
    assert all(r["citation"] is None for r in result["records"]) and result["status"] == "ok"
    assert [d["citation"] for d in result["datasets"]] == [None, None] and "citations-partial" not in result["flags"]

    runtime2, router2, _ = make_runtime()
    router2.on(c.GBIF_HOST, lambda request: json_response(search_payload(records)) if request.url.path.endswith("search") else httpx.Response(500))
    failed = species_context(runtime2, SITE, None, None, None)
    assert failed["status"] == "ok" and failed["datasets"] == [] and "citations-partial" in failed["flags"]
    assert all(r["citation"] is None for r in failed["records"])


def test_at_most_five_datasets_are_looked_up_per_response() -> None:
    keys = [f"00000000-0000-4000-8000-00000000000{i}" for i in range(8)]
    records = [occurrence(i + 1, datasetKey=key) for i, key in enumerate(keys)]
    runtime, router, _ = gbif_runtime(lambda request: json_response(search_payload(records)))
    result = species_context(runtime, SITE, None, None, None)
    assert len(result["datasets"]) == 5 and "citations-partial" in result["flags"]
    assert sum(1 for r in router.requests if r.url.path.startswith("/v1/dataset/")) == 5
    assert sum(1 for r in result["records"] if r["citation"]) == 5


def test_the_search_is_cached_and_a_different_filter_is_a_different_entry() -> None:
    runtime, router, clock = gbif_runtime(settings=ExternalSettings(cache_ttl_seconds=60.0, max_retries=0))
    first = species_context(runtime, SITE, None, None, None)
    again = species_context(runtime, SITE, None, None, None)
    assert (first["cached"], again["cached"]) == (False, True) and len(search_requests(router)) == 1
    near = LocatedSite("N", "N", "waterbase-site", "x", "IT", 45.071, 7.691, "river")
    assert species_context(runtime, near, None, None, None)["cached"] is True
    assert species_context(runtime, SITE, "odonata", None, None)["cached"] is False
    clock.advance(61)
    assert species_context(runtime, SITE, None, None, None)["cached"] is False


def test_the_cached_value_is_not_changed_by_a_caller() -> None:
    runtime, _, _ = gbif_runtime()
    first = species_context(runtime, SITE, None, None, None)
    first["records"][0]["licence"] = "tampered"
    assert species_context(runtime, SITE, None, None, None)["records"][0]["licence"] == "CC-BY-NC-4.0"


@pytest.mark.parametrize(
    "payload",
    [{}, {"count": "3", "results": []}, {"count": -1, "results": []}, {"count": True, "results": []}, {"count": 1, "results": "x"},
     {"count": 3, "results": [occurrence(i) for i in range(1, 100)]}],
)
def test_malformed_search_answers_are_bad_responses(payload: dict) -> None:
    runtime, _, _ = gbif_runtime(lambda request: json_response(payload))
    result = species_context(runtime, SITE, None, None, None, 5)
    assert result["status"] == "external-unavailable" and result["reason"] == c.REASON_BAD_RESPONSE and result["records"] == []


def test_provider_problems_are_external_unavailable() -> None:
    for status, reason in [(429, c.REASON_RATE_LIMITED), (503, c.REASON_HTTP), (404, c.REASON_HTTP)]:
        runtime, _, _ = gbif_runtime(lambda request, s=status: httpx.Response(s))
        result = species_context(runtime, SITE, None, None, None)
        assert result["status"] == "external-unavailable" and result["reason"] == reason
        assert result["origin"] == "external-gbif" and result["attribution"] and result["records"] == []
        assert result["search"]["half_side_km"] == 5.0

    def timeout(request):
        raise httpx.ConnectTimeout("slow", request=request)

    runtime, _, _ = gbif_runtime(timeout)
    assert species_context(runtime, SITE, None, None, None)["reason"] == c.REASON_TIMEOUT


def test_budget_and_switches() -> None:
    runtime, router, _ = gbif_runtime(settings=ExternalSettings(gbif_per_minute=1, max_retries=0))
    first = species_context(runtime, SITE, None, None, None)  # the search takes the one request; the citation lookup is refused
    assert first["status"] == "ok" and first["datasets"] == [] and "citations-partial" in first["flags"]
    second = species_context(runtime, SITE, "odonata", None, None)
    assert second["status"] == "external-unavailable" and second["reason"] == c.REASON_BUDGET
    for settings in (ExternalSettings(enabled=False), ExternalSettings(gbif_enabled=False)):
        off, router_off, _ = gbif_runtime(settings=settings)
        assert species_context(off, SITE, None, None, None)["reason"] == c.REASON_DISABLED
        assert router_off.requests == []
    assert router.count() == 1


def test_the_default_http_layer_sends_the_user_agent_with_the_operator_contact() -> None:
    from oah.external.runtime import ExternalRuntime

    configured = ExternalRuntime(ExternalSettings(contact_url="https://example.org/contact"))
    assert configured._http._headers["User-Agent"] == "OneAquaHealth/0.1 (research prototype; +https://example.org/contact)"
    assert configured._http._headers["Accept"] == "application/json"
    assert ExternalRuntime(ExternalSettings())._http._headers["User-Agent"] == "OneAquaHealth/0.1 (research prototype)"


def test_a_site_near_a_pole_is_an_input_error() -> None:
    runtime, router, _ = gbif_runtime()
    polar = LocatedSite("P", "P", "waterbase-site", "x", "NO", 85.0, 10.0, "river")
    with pytest.raises(ExternalInputError):
        species_context(runtime, polar, None, None, None)
    assert router.requests == []


def test_the_default_limit_and_maximum_are_the_documented_ones() -> None:
    assert (gbif.DEFAULT_LIMIT, gbif.MAX_LIMIT, gbif.MAX_CITATION_DATASETS) == (50, 200, 5)
