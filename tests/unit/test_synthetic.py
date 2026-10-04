"""Synthetic campaign contracts; all records here are deliberately simulated."""

from collections import defaultdict

import pytest
from fhir.resources.R4B.codesystem import CodeSystem
from fhir.resources.R4B.observation import Observation
from fhir.resources.R4B.provenance import Provenance

from oah.fhir.output.export import build_findings_bundle
from oah.ingest.sources import RealObservationSource, SourceRecord, assert_single_origin
from oah.qc.report import build_report
from oah.synthetic.campaign import generate_campaign
from oah.synthetic.fhir import (
    OBSERVER_IDENTIFIER_SYSTEM,
    TAXA_CODE_SYSTEM,
    build_synthetic_batch,
    rebuild_annotation_table,
)
from oah.synthetic.source import SyntheticObservationSource

SITE_LABELS = ("Loc-Almyros", "Loc-Benevento")


def _campaign(seed=42):
    # Synthetic test data: real Location ids are labels only, never source data.
    return generate_campaign(
        seed=seed,
        site_ids=SITE_LABELS,
        observer_count=4,
        specimens_per_site=3,
        annotators_per_specimen=3,
    )


def test_campaign_is_deterministic_for_a_seed_and_retains_ground_truth():
    first = _campaign()
    second = _campaign()
    assert first == second
    assert all(specimen.true_family in first.taxa_families for specimen in first.specimens)
    assert all(obs.reported_family in first.taxa_families for obs in first.observations)


def test_each_specimen_has_at_least_two_distinct_annotators():
    campaign = _campaign()
    specimen_observers = defaultdict(set)
    for obs in campaign.observations:
        specimen_observers[obs.specimen_id].add(obs.observer_id)
    assert len(specimen_observers) == len(campaign.specimens)
    for specimen_id, observers in specimen_observers.items():
        assert len(observers) >= 2
        assert len(observers) == 3


def test_weak_observers_exist_and_confusion_matrices_sum_to_one():
    campaign = _campaign()
    assert any(0.30 <= obs.skill <= 0.55 for obs in campaign.observers)
    for obs in campaign.observers:
        for row in obs.confusion_matrix:
            assert sum(row) == pytest.approx(1.0)


def test_synthetic_fhir_resources_are_tagged_and_use_project_taxa_codes():
    campaign = _campaign()
    batch = build_synthetic_batch(campaign)
    assert batch.provenance["reason"][0]["text"].startswith("synthetic, seed=42")

    CodeSystem.model_validate(batch.code_system)
    Provenance.model_validate(batch.provenance)

    assert batch.code_system["text"]["status"] == "generated"
    assert batch.provenance["text"]["status"] == "generated"

    for record in batch.records:
        Observation.model_validate(record.resource)
        tags = record.resource["meta"]["tag"]
        assert {tag["code"] for tag in tags} == {"synthetic"}
        assert record.resource["code"]["coding"][0]["system"] == TAXA_CODE_SYSTEM
        assert record.resource["specimen"]["reference"].startswith("Specimen/")
        assert record.resource["performer"][0]["identifier"]["system"] == OBSERVER_IDENTIFIER_SYSTEM
        assert record.resource["text"]["status"] == "generated"
        assert record.origin == "synthetic"
    assert {tag["code"] for tag in batch.provenance["meta"]["tag"]} == {"synthetic"}


def test_ground_truth_stays_out_of_fhir_resources():
    campaign = _campaign()
    batch = build_synthetic_batch(campaign)
    specimen_true_families = {spec.specimen_id: spec.true_family for spec in campaign.specimens}
    for record in batch.records:
        res = record.resource
        spec_ref = res["specimen"]["reference"]
        spec_id = spec_ref.split("Specimen/")[-1]
        assert "true_family" not in res
        assert "ground_truth" not in res
        true_fam = specimen_true_families[spec_id]
        if res["valueCodeableConcept"]["coding"][0]["code"] != true_fam:
            assert true_fam not in res["valueCodeableConcept"]["coding"][0]["code"]


def test_rebuild_annotation_table_round_trip():
    campaign = _campaign()
    batch = build_synthetic_batch(campaign)
    rebuilt = rebuild_annotation_table(batch.records)
    expected = [
        (obs.specimen_id, obs.observer_id, obs.reported_family)
        for obs in campaign.observations
    ]
    assert rebuilt == expected


def test_sources_expose_origin_and_reports_preserve_it():
    batch = build_synthetic_batch(_campaign())
    records = list(SyntheticObservationSource(batch).observations())
    assert assert_single_origin(records) == "synthetic"
    assert build_report(records)["origin"] == "synthetic"


def test_real_source_uses_the_same_record_shape_with_real_origin():
    class FakeClient:
        def pages(self, resource_type):
            assert resource_type == "Observation"
            yield [{"resourceType": "Observation", "id": "Obs-Almyros-sample"}]

    records = list(RealObservationSource(FakeClient()).observations())
    assert records == [
        SourceRecord({"resourceType": "Observation", "id": "Obs-Almyros-sample"}, "real-sandbox")
    ]


def test_mixing_guard_rejects_real_and_synthetic_records():
    synthetic_record = build_synthetic_batch(_campaign()).records[0]
    real_record = SourceRecord({"resourceType": "Observation", "id": "real"}, "real-sandbox")
    with pytest.raises(ValueError, match="must not mix"):
        assert_single_origin([real_record, synthetic_record])


def test_exporter_refuses_a_synthetic_batch_as_real_derived():
    batch = build_synthetic_batch(_campaign())
    with pytest.raises(ValueError, match="must not be exported as real-derived"):
        build_findings_bundle(batch.records, "2026-09-21T00:00:00+00:00", "https://sandbox.test")
