"""Apply water quality indices to real FHIR sandbox observations per location.

See ``oah.indices.water_parameter_limits`` for the objective limits, unit conversions, and
plausibility checks, and ``oah.indices.sandbox_loader`` for sandbox-resource loading. This module
holds only the CCME WQI pipeline itself and the site-listing join used for the map view.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from oah.config import load_settings
from oah.indices.limit_overrides import active_report, ensure_overrides_loaded
from oah.indices.limit_verification import verification_label
from oah.indices.oxygen import (
    DISSOLVED_OXYGEN,
    SATURATION_PARAMETER,
    WATER_TEMPERATURE,
    collect_water_temperatures,
    effective_key,
    saturation_test,
)
from oah.indices.regimes import (
    COUNTRY_OXYGEN_DEVIATION_LIMIT,
    COUNTRY_TEMPERATURE_INTERPRETIVE,
    DEFAULT_REGIME,
    SURFACE,
    countries_by_location_ref,
    limit_basis,
    observation_instant,
    regimes_by_location_ref,
    resolve_limit,
)
from oah.indices.sandbox_loader import fetch_sandbox_locations, fetch_sandbox_observations
from oah.indices.site_kind import site_kind
from oah.indices.water_parameter_limits import (
    PARAMETER_UNITS,
    TWO_SIDED_LIMITS,
    classify_quantity,
    classify_range_quantity,
    convert_to_unit,
    exact_numeric_value,
    is_health_measure_profile,
    is_physically_possible,
    is_water_profile,
    match_closed_parameter,
    representative_quantity,
    resolve_range_limit,
)
from oah.indices.water_quality import ccme_wqi, classify_ccme_wqi, excursion

# Non-compensatory veto (project convention, NOT taken from CCME 2001 or the WFD): a parameter whose
# worst test departs from its objective by at least this relative excursion (1.0 = twice the limit,
# or half a minimum) triggers the veto, whatever the composite index says. Inspired by the one-out,
# all-out principle of the Water Framework Directive, but far less sensitive to a single marginal test.
VETO_EXCURSION = 1.0
# Confidence drops to low when at least this share of a site's scorable observations had to be
# excluded for data-quality reasons (project convention, not sourced).
MAX_EXCLUDED_SHARE = 0.5
# Composite classes for which a triggered veto counts as "eclipsing" (the index hides a severe exceedance).
ECLIPSABLE_CCME_CLASSES = frozenset({"Excellent", "Good", "Fair"})


# CCME's five official bands (classify_ccme_wqi) collapsed to three UI-facing buckets, for a
# simple traffic-light map marker; the underlying score and class are always included too, so
# nothing is lost -- this mapping only controls color grouping, not the reported score.
UI_STATUS_BY_CCME_CLASS: dict[str, str] = {
    "Excellent": "good",
    "Good": "good",
    "Fair": "moderate",
    "Marginal": "moderate",
    "Poor": "poor",
}


# Dataset-wide counters (all locations) that explain what the index left out; site-level counts are in each entry.
DATA_QUALITY_KEYS = (
    "skipped_censored_quantities",
    "censored_quantities_counted_as_pass",
    "skipped_qc_inconsistent_observations",
    "skipped_physically_impossible_observations",
    "skipped_unit_mismatch_observations",
    "skipped_non_finite_observations",
    "skipped_invalid_quantity_observations",
    "skipped_no_subject_observations",
    "skipped_surface_limit_needs_hardness_observations",
    "skipped_interpretive_only_observations",
    "skipped_no_temperature_for_saturation_observations",
    "skipped_ambiguous_temperature_for_saturation_observations",
    "skipped_unusable_temperature_for_saturation_observations",
    "skipped_no_representative_observations",
)


def _basis_with_verification(parameter: str, regime: str, country: str | None) -> str:
    """Where a limit comes from, and whether a person has verified it (see limit_verification)."""
    return f"{limit_basis(parameter, regime, country)} {verification_label(regime, country, parameter)}"


def data_quality(results: dict[str, Any]) -> dict[str, Any]:
    """The dataset-wide data-quality counters of an ``apply_ccme_wqi_to_sandbox`` result."""
    return {key: results[key] for key in DATA_QUALITY_KEYS}


def limits_note(results: dict[str, Any]) -> str:
    """Where the objective limits come from and why they are only proxies (shown to every consumer)."""
    return str(results["objective_limits_source"])


def veto_assessment(measurements: Sequence[tuple[str, float, float, bool]], wqi_score: float) -> dict[str, Any]:
    """Non-compensatory check on the same measurements the CCME WQI used.

    ``veto_parameters`` lists every parameter whose worst excursion is at least ``VETO_EXCURSION``,
    worst first. ``eclipsed`` is True when the veto fired although the composite class is Excellent,
    Good or Fair.
    """
    worst: dict[str, tuple[float, float, float]] = {}  # parameter -> (excursion, observed, limit) of its worst test
    for parameter, observed, limit, is_lower in measurements:
        candidate = (excursion(observed, limit, is_lower), observed, limit)
        if parameter not in worst or candidate[0] > worst[parameter][0]:
            worst[parameter] = candidate
    fired: list[dict[str, Any]] = [
        {
            "parameter": name,
            "worst_excursion": exc,  # relative excess over the limit: 0 = within limit, 1 = twice the limit
            "times_limit": 1.0 + exc,  # how many times the limit the worst reading was (or 1/x below a minimum)
            "worst_value": observed,
            "limit": limit,
            "unit": PARAMETER_UNITS.get(name),
        }
        for name, (exc, observed, limit) in worst.items()
        if exc >= VETO_EXCURSION
    ]
    triggered = sorted(fired, key=lambda item: (-float(item["worst_excursion"]), str(item["parameter"])))
    return {
        "worst_parameter_excursion": max((entry[0] for entry in worst.values()), default=0.0),
        "veto_triggered": bool(triggered),
        "veto_parameters": triggered,
        "eclipsed": bool(triggered) and classify_ccme_wqi(wqi_score) in ECLIPSABLE_CCME_CLASSES,
    }


def list_sites_with_status(
    observations: Sequence[dict[str, Any]] | None = None,
    locations: Sequence[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Join each real sandbox Location's own position to its CCME WQI result, if computable.

    Adds no new computation: the WQI score comes from apply_ccme_wqi_to_sandbox and its class
    from classify_ccme_wqi, both already tested elsewhere; this only joins that result to each
    Location resource's own name and position (latitude/longitude) for display on a map.
    Locations without a usable position (position.latitude/longitude) are skipped entirely --
    they cannot be placed on a map.
    """
    if locations is None:
        locations = fetch_sandbox_locations()

    wqi_result = apply_ccme_wqi_to_sandbox(observations, locations)
    evaluated_by_ref = {entry["location_ref"]: entry for entry in wqi_result["evaluated_locations"]}
    skipped_by_ref = {entry["location_ref"]: entry for entry in wqi_result["skipped_locations"]}
    countries = countries_by_location_ref(locations)  # resolvable country, also for sites that were not evaluated

    sites: list[dict[str, Any]] = []
    for location in locations:
        location_id = location.get("id")
        position = location.get("position", {})
        latitude = position.get("latitude")
        longitude = position.get("longitude")
        if not location_id or latitude is None or longitude is None:
            continue

        location_ref = f"Location/{location_id}"
        name = location.get("name", location_id)
        evaluated = evaluated_by_ref.get(location_ref)
        kind = site_kind(location)

        if evaluated is not None:
            ccme_class = classify_ccme_wqi(evaluated["ccme_wqi"])
            sites.append(
                {
                    "id": location_id,
                    "name": name,
                    "latitude": latitude,
                    "longitude": longitude,
                    "kind": kind,
                    "status": "evaluated",
                    "ccme_wqi": evaluated["ccme_wqi"],
                    "ccme_class": ccme_class,
                    "ui_status": UI_STATUS_BY_CCME_CLASS[ccme_class],
                    "limit_regime": evaluated.get("limit_regime"),
                    "limit_country": evaluated.get("limit_country"),
                    "confidence": evaluated["confidence"],
                    "veto_triggered": evaluated.get("veto_triggered", False),
                    "eclipsed": evaluated.get("eclipsed", False),
                }
            )
        else:
            skipped = skipped_by_ref.get(location_ref)
            sites.append(
                {
                    "id": location_id,
                    "name": name,
                    "latitude": latitude,
                    "longitude": longitude,
                    "kind": kind,
                    "status": "skipped",
                    "ccme_wqi": None,
                    "ccme_class": None,
                    "ui_status": "unavailable",
                    "limit_country": countries.get(location_ref),
                    "reason": (
                        skipped["reason"]
                        if skipped is not None
                        else "No sandbox Observations reference this location."
                    ),
                }
            )
    return sites


def apply_ccme_wqi_to_sandbox(
    observations: Sequence[dict[str, Any]] | None = None,
    locations: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Extract physicochemical measurements by Location and compute CCME WQI per site.

    Enforces strict profile filtering (water profiles only) and exact closed FHIR code matching.
    ``locations`` decides each site's limit regime (``oah.indices.regimes``); without it every site
    uses the default drinking-water regime.
    """
    ensure_overrides_loaded(load_settings().limits_file)  # the user's limits file, if any (re-read when it changes)
    if observations is None:
        observations = fetch_sandbox_observations()
    regimes = regimes_by_location_ref(locations)
    countries = countries_by_location_ref(locations)
    temperatures = collect_water_temperatures(observations)
    site_regimes: dict[str, str] = {}

    measurements_by_site: dict[str, list[tuple[str, float, float, bool]]] = {}
    site_observation_counts: dict[str, int] = {}

    skipped_health_measure_count = 0
    skipped_non_water_profile_count = 0
    skipped_unmapped_code_count = 0
    skipped_censored_count = 0
    censored_pass_count = 0
    skipped_by_reason: dict[str, int] = {}
    mapped_by_site: dict[str, int] = {}
    excluded_by_site: dict[str, int] = {}

    for obs in observations:
        profiles = obs.get("meta", {}).get("profile", [])
        if is_health_measure_profile(profiles):
            skipped_health_measure_count += 1
            continue

        if not is_water_profile(profiles):
            skipped_non_water_profile_count += 1
            continue

        loc_ref = obs.get("subject", {}).get("reference", "unknown")
        if not loc_ref or loc_ref == "unknown":
            skipped_by_reason["no-subject"] = skipped_by_reason.get("no-subject", 0) + 1
            continue

        if loc_ref not in site_observation_counts:
            site_observation_counts[loc_ref] = 0
            measurements_by_site[loc_ref] = []

        site_observation_counts[loc_ref] += 1

        matched = match_closed_parameter(obs)
        if matched is None:
            skipped_unmapped_code_count += 1
            continue

        param_name, limit, is_lower = matched
        regime = regimes.get(loc_ref, DEFAULT_REGIME)
        country = countries.get(loc_ref)
        if regime == SURFACE and param_name == WATER_TEMPERATURE and country in COUNTRY_TEMPERATURE_INTERPRETIVE:
            skipped_by_reason["interpretive-only"] = skipped_by_reason.get("interpretive-only", 0) + 1
            continue
        regime_limit = resolve_limit(param_name, limit, regime, observation_instant(obs), country)
        if regime_limit is None:
            skipped_by_reason["surface-limit-needs-hardness"] = skipped_by_reason.get("surface-limit-needs-hardness", 0) + 1
            continue
        limit = regime_limit
        site_regimes[loc_ref] = regime
        mapped_by_site[loc_ref] = mapped_by_site.get(loc_ref, 0) + 1

        quantity, reason = representative_quantity(obs)
        if quantity is None:
            reason = reason or "no-quantity"
            skipped_by_reason[reason] = skipped_by_reason.get(reason, 0) + 1
            if reason == "qc-inconsistent":
                excluded_by_site[loc_ref] = excluded_by_site.get(loc_ref, 0) + 1
            continue
        raw_value = quantity.get("value")
        if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool) and not math.isfinite(raw_value):
            skipped_by_reason["non-finite-value"] = skipped_by_reason.get("non-finite-value", 0) + 1
            excluded_by_site[loc_ref] = excluded_by_site.get(loc_ref, 0) + 1
            continue
        if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
            converted = convert_to_unit(float(raw_value), quantity.get("code"), PARAMETER_UNITS[param_name])
            if converted is None:
                skipped_by_reason["unit-mismatch"] = skipped_by_reason.get("unit-mismatch", 0) + 1
                excluded_by_site[loc_ref] = excluded_by_site.get(loc_ref, 0) + 1
                continue
            quantity = {**quantity, "value": converted}
        value_range = TWO_SIDED_LIMITS.get(param_name)
        oxygen_limit = COUNTRY_OXYGEN_DEVIATION_LIMIT.get(country or "") if regime == SURFACE else None
        if param_name == DISSOLVED_OXYGEN and oxygen_limit is not None:
            concentration = exact_numeric_value(quantity)
            if concentration is not None and not is_physically_possible(DISSOLVED_OXYGEN, concentration):
                # The deviation is an absolute value and always looks plausible: judge the raw mg/L instead.
                skipped_by_reason["physically-impossible"] = skipped_by_reason.get("physically-impossible", 0) + 1
                excluded_by_site[loc_ref] = excluded_by_site.get(loc_ref, 0) + 1
                continue
            kind, value = saturation_test(quantity, temperatures.get((loc_ref, effective_key(obs) or "")))
            if kind.endswith("temperature"):
                reason_key = f"{kind}-for-saturation"  # no-, ambiguous- or unusable-temperature-for-saturation
                skipped_by_reason[reason_key] = skipped_by_reason.get(reason_key, 0) + 1
                excluded_by_site[loc_ref] = excluded_by_site.get(loc_ref, 0) + 1
                continue
            param_name, limit, is_lower = SATURATION_PARAMETER, oxygen_limit, False
        elif value_range is None:
            kind, value = classify_quantity(quantity, limit, is_lower)
        else:
            kind, value = classify_range_quantity(quantity)
        if value is not None and not is_physically_possible(param_name, value):
            skipped_by_reason["physically-impossible"] = skipped_by_reason.get("physically-impossible", 0) + 1
            excluded_by_site[loc_ref] = excluded_by_site.get(loc_ref, 0) + 1
            continue
        if value is not None and value_range is not None:
            limit, is_lower = resolve_range_limit(value, *value_range)
        if value is not None:
            measurements_by_site[loc_ref].append((param_name, value, limit, is_lower))
            if kind == "pass-by-bound":
                censored_pass_count += 1
        elif kind == "indeterminate":
            skipped_censored_count += 1
        else:  # "invalid": no usable number; counted so that scorable == evaluated + skipped
            skipped_by_reason["invalid-quantity"] = skipped_by_reason.get("invalid-quantity", 0) + 1
            excluded_by_site[loc_ref] = excluded_by_site.get(loc_ref, 0) + 1

    evaluated_locations = []
    skipped_locations = []

    for site_ref in sorted(site_observation_counts.keys()):
        m_list = measurements_by_site.get(site_ref, [])
        total_obs = site_observation_counts[site_ref]

        if not m_list:
            skipped_locations.append(
                {
                    "location_ref": site_ref,
                    "total_observations": total_obs,
                    "reason": f"No evaluable physicochemical observations matching closed water quality limits present for {site_ref}.",
                }
            )
        else:
            distinct_params = {name for name, _, _, _ in m_list}
            distinct_count = len(distinct_params)
            wqi_score = ccme_wqi(m_list)
            failed_count = sum(
                1 for _, observed, limit, is_low in m_list if (observed < limit if is_low else observed > limit)
            )
            mapped = mapped_by_site.get(site_ref, 0)
            excluded = excluded_by_site.get(site_ref, 0)
            excluded_share = excluded / mapped if mapped else 0.0
            notes = []
            if distinct_count < 4:
                notes.append("below CCME 2001's recommended minimum of 4 variables")
            if excluded_share >= MAX_EXCLUDED_SHARE:
                notes.append(
                    f"{excluded} of {mapped} scorable observations ({excluded_share:.0%}) were excluded as "
                    "internally inconsistent or physically impossible"
                )
            confidence = "low_confidence" if notes else "normal"
            confidence_note = f"low confidence ({'; '.join(notes)})" if notes else ""

            evaluated_locations.append(
                {
                    "location_ref": site_ref,
                    "total_observations": total_obs,
                    "evaluable_measurements": len(m_list),
                    "excluded_data_quality_observations": excluded,
                    "scorable_observations": mapped,
                    "distinct_parameters_count": distinct_count,
                    "failed_measurements": failed_count,
                    "ccme_wqi": wqi_score,
                    "limit_regime": site_regimes.get(site_ref, DEFAULT_REGIME),
                    "limit_country": countries.get(site_ref),
                    "limit_basis": {
                        name: _basis_with_verification(name, site_regimes.get(site_ref, DEFAULT_REGIME), countries.get(site_ref))
                        for name in sorted(distinct_params)
                    },
                    **veto_assessment(m_list, wqi_score),
                    "confidence": confidence,
                    "confidence_note": confidence_note,
                }
            )

    return {
        "input_origin": "real-sandbox",
        "total_observations_analyzed": len(observations),
        "skipped_health_measure_observations": skipped_health_measure_count,
        "skipped_non_water_profile_observations": skipped_non_water_profile_count,
        "skipped_unmapped_code_observations": skipped_unmapped_code_count,
        "skipped_censored_quantities": skipped_censored_count,
        "censored_quantities_counted_as_pass": censored_pass_count,
        "skipped_unit_mismatch_observations": skipped_by_reason.get("unit-mismatch", 0),
        "skipped_physically_impossible_observations": skipped_by_reason.get("physically-impossible", 0),
        "skipped_non_finite_observations": skipped_by_reason.get("non-finite-value", 0),
        "skipped_surface_limit_needs_hardness_observations": skipped_by_reason.get("surface-limit-needs-hardness", 0),
        "skipped_interpretive_only_observations": skipped_by_reason.get("interpretive-only", 0),
        "skipped_no_temperature_for_saturation_observations": skipped_by_reason.get("no-temperature-for-saturation", 0),
        "skipped_ambiguous_temperature_for_saturation_observations": skipped_by_reason.get(
            "ambiguous-temperature-for-saturation", 0
        ),
        "skipped_unusable_temperature_for_saturation_observations": skipped_by_reason.get(
            "unusable-temperature-for-saturation", 0
        ),
        "skipped_invalid_quantity_observations": skipped_by_reason.get("invalid-quantity", 0),
        "skipped_no_subject_observations": skipped_by_reason.get("no-subject", 0),
        "skipped_qc_inconsistent_observations": skipped_by_reason.get("qc-inconsistent", 0),
        "skipped_no_representative_observations": skipped_by_reason.get("no-representative-statistic", 0) + skipped_by_reason.get("no-quantity", 0),
        "total_locations_found": len(site_observation_counts),
        "evaluated_locations_count": len(evaluated_locations),
        "skipped_locations_count": len(skipped_locations),
        "evaluated_locations": evaluated_locations,
        "skipped_locations": skipped_locations,
        "limit_overrides": (
            {"file": report.path, "note": report.note, "limits": report.limits, "locations": report.locations}
            if (report := active_report()) is not None
            else None
        ),
        "objective_limits_source": (
            "Reference values, not legal limits: EU drinking-water values by default; river sites use EU EQS "
            "and national IT LIMeco / GR HWQI values where sourced; the rest are proxies (see docs)."
        ),
        "macroinvertebrate_indices_note": (
            "Macroinvertebrate indices (BMWP, ASPT, IBMWP, Shannon, Simpson, Pielou, Chao1) "
            "were NOT computed on real sandbox data because no macroinvertebrate count records exist in the sandbox."
        ),
    }
