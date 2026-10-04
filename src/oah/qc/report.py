"""Aggregate non-mutating QC reporting for sandbox Observations."""
from __future__ import annotations
from collections import Counter, defaultdict
from oah.config import sandbox_url
from oah.ingest.classification import classify_observation
from oah.ingest.sources import assert_single_origin, source_records
from oah.qc.policy import ALLOWED_UCUM_CODES, REVIEW_UCUM_CODES
from oah.qc.statistics import component_statistics
from oah.timeutil import format_utc, utc_now

def build_report(observations, allowed_ucum=None, default_origin=None):
    allowed = set(ALLOWED_UCUM_CODES if allowed_ucum is None else allowed_ucum)
    allowed.update(REVIEW_UCUM_CODES)
    records = source_records(observations, default_origin)
    input_origin = assert_single_origin(records) or default_origin
    if input_origin is None:
        raise ValueError("Cannot determine the origin of an empty batch: pass default_origin.")
    profiles, findings, sites, examples, origins = Counter(), Counter(), Counter(), defaultdict(list), Counter()
    missing, ph_review, codes = 0, 0, set()
    for source_record in records:
        observation = source_record.resource
        origins[classify_observation(observation)] += 1
        profile = next(iter(observation.get("meta", {}).get("profile", [])), "no profile")
        profiles[profile] += 1
        sites[observation.get("subject", {}).get("reference", "unknown")] += 1
        for component in observation.get("component", []):
            quantity = component.get("valueQuantity", {})
            if quantity.get("system") == "http://unitsofmeasure.org":
                if "code" not in quantity:
                    missing += 1
                else:
                    codes.add(quantity["code"])
                    if quantity["code"] in REVIEW_UCUM_CODES:
                        ph_review += 1
        for finding in component_statistics(observation, allowed):
            findings[finding.code] += 1
            if len(examples[finding.code]) < 20:
                examples[finding.code].append(finding.resource_id)
    return {"generated_at_utc": format_utc(utc_now()), "source": sandbox_url(), "origin": input_origin, "total_observations": len(records), "observation_origin_counts": {"official": origins["official"], "other": origins["other"]}, "profiles": dict(profiles), "findings": dict(findings), "sites": dict(sites), "examples": {k: {"total": findings[k], "ids": v} for k, v in examples.items()}, "quantity_values_without_code": missing, "quantity_codes": sorted(codes), "pH_code_to_review": ph_review, "findings_to_review": ["pH"] if ph_review else []}
