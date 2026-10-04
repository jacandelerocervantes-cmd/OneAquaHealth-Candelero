"""FHIR rendering for explicitly labeled synthetic campaign data."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from oah.fhir.output.builders import ORIGIN_SYSTEM
from oah.ingest.sources import SourceRecord
from oah.synthetic.campaign import Campaign, CampaignObservation

TAXA_CODE_SYSTEM = "https://oneaquahealth-hackathon.example/CodeSystem/synthetic-taxa-family"
OBSERVER_IDENTIFIER_SYSTEM = "https://oneaquahealth-hackathon.example/observer-id"


def _identifier(campaign: Campaign, observation: CampaignObservation) -> str:
    stable = ":".join(
        (
            str(campaign.seed),
            observation.specimen_id,
            observation.site_id,
            observation.observer_id,
            observation.reported_family,
            observation.timestamp.isoformat(),
        )
    )
    return str(uuid5(NAMESPACE_URL, stable))


def synthetic_observation(campaign: Campaign, observation: CampaignObservation) -> dict:
    """Build one R4 Observation with a project-defined synthetic taxa code."""
    return {
        "resourceType": "Observation",
        "id": _identifier(campaign, observation),
        "meta": {"tag": [{"system": ORIGIN_SYSTEM, "code": "synthetic"}]},
        "text": {
            "status": "generated",
            "div": (
                f'<div xmlns="http://www.w3.org/1999/xhtml">'
                f"Synthetic observation of {observation.reported_family} "
                f"for specimen {observation.specimen_id} at site {observation.site_id} "
                f"by observer {observation.observer_id}</div>"
            ),
        },
        "status": "final",
        "code": {
            "coding": [
                {
                    "system": TAXA_CODE_SYSTEM,
                    "code": "reported-family",
                    "display": "Reported macroinvertebrate family",
                }
            ]
        },
        "subject": {"reference": f"Location/{observation.site_id}"},
        "specimen": {"reference": f"Specimen/{observation.specimen_id}"},
        "performer": [
            {
                "identifier": {
                    "system": OBSERVER_IDENTIFIER_SYSTEM,
                    "value": observation.observer_id,
                }
            }
        ],
        "effectiveDateTime": observation.timestamp.isoformat(),
        "valueCodeableConcept": {
            "coding": [
                {
                    "system": TAXA_CODE_SYSTEM,
                    "code": observation.reported_family,
                    "display": observation.reported_family,
                }
            ]
        },
    }


def synthetic_taxa_code_system(campaign: Campaign) -> dict:
    """Emit a project-defined CodeSystem resource for synthetic taxa families."""
    concepts = [
        {"code": family, "display": family}
        for family in campaign.taxa_families
    ]
    concepts.append({"code": "reported-family", "display": "Reported macroinvertebrate family"})
    return {
        "resourceType": "CodeSystem",
        "id": str(uuid5(NAMESPACE_URL, f"synthetic-codesystem:{campaign.seed}")),
        "meta": {"tag": [{"system": ORIGIN_SYSTEM, "code": "synthetic"}]},
        "text": {
            "status": "generated",
            "div": '<div xmlns="http://www.w3.org/1999/xhtml">Synthetic taxa family CodeSystem</div>',
        },
        "url": TAXA_CODE_SYSTEM,
        "status": "active",
        "content": "complete",
        "concept": concepts,
    }


def synthetic_provenance(campaign: Campaign, observations: list[dict]) -> dict:
    """Build batch Provenance that declares the simulator seed and version."""
    return {
        "resourceType": "Provenance",
        "id": str(uuid5(NAMESPACE_URL, f"synthetic:{campaign.seed}:{campaign.generator_version}")),
        "meta": {"tag": [{"system": ORIGIN_SYSTEM, "code": "synthetic"}]},
        "text": {
            "status": "generated",
            "div": (
                f'<div xmlns="http://www.w3.org/1999/xhtml">'
                f"Synthetic campaign provenance for seed {campaign.seed}</div>"
            ),
        },
        "recorded": "2026-01-01T00:00:00+00:00",
        "target": [{"reference": f"Observation/{observation['id']}"} for observation in observations],
        "agent": [{"who": {"display": "OneAquaHealth synthetic campaign generator"}}],
        "reason": [
            {
                "text": (
                    f"synthetic, seed={campaign.seed}, generator version={campaign.generator_version}"
                )
            }
        ],
    }


@dataclass(frozen=True)
class SyntheticBatch:
    """Synthetic FHIR Observation records plus mandatory batch Provenance and CodeSystem."""

    records: tuple[SourceRecord, ...]
    provenance: dict
    code_system: dict


def build_synthetic_batch(campaign: Campaign) -> SyntheticBatch:
    """Render all campaign observations and retain their synthetic origin."""
    observations = [synthetic_observation(campaign, observation) for observation in campaign.observations]
    code_system = synthetic_taxa_code_system(campaign)
    provenance = synthetic_provenance(campaign, observations)
    return SyntheticBatch(
        tuple(SourceRecord(observation, "synthetic") for observation in observations),
        provenance,
        code_system,
    )


def rebuild_annotation_table(
    fhir_observations: Sequence[dict | SourceRecord],
) -> list[tuple[str, str, str]]:
    """Rebuild annotation table (specimen_id, observer_id, label) from FHIR Observations ONLY."""
    annotations = []
    for item in fhir_observations:
        resource = item.resource if isinstance(item, SourceRecord) else item
        if resource.get("resourceType") != "Observation":
            continue
        specimen_ref = resource.get("specimen", {}).get("reference", "")
        specimen_id = specimen_ref.split("Specimen/")[-1] if "Specimen/" in specimen_ref else specimen_ref

        performers = resource.get("performer", [])
        observer_id = ""
        if performers and isinstance(performers, list):
            identifier = performers[0].get("identifier", {})
            observer_id = identifier.get("value", "")

        value_cc = resource.get("valueCodeableConcept", {})
        codings = value_cc.get("coding", [])
        label = codings[0].get("code", "") if codings else ""

        annotations.append((specimen_id, observer_id, label))
    return annotations
