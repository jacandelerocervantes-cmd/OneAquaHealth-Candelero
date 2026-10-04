import type { Schema } from "./api";

/**
 * Used by the MOCK backend only (`src/lib/server/mock`): the same shape as the real `GET /sites/{id}/fhir` of the Python
 * backend (`src/oah/fhir/output/measurements.py`, the authority), so the mock mode and the tests follow it. Rules
 * (docs/fhir_mapping.md): no code is invented, so a parameter is written as text only (no `coding`); a UCUM unit code is
 * added only for units known to be written the UCUM way; the data origin is a project-defined tag (the same system as the
 * backend exports); the Bundle carries a Provenance naming the software and the source. No claim of conformance to the
 * OneAquaHealth profiles.
 */

export const ORIGIN_SYSTEM = "https://oneaquahealth-hackathon.example/CodeSystem/data-origin";
export const LOCATION_ID_SYSTEM = "https://oneaquahealth-hackathon.example/location-id";
const UCUM = "http://unitsofmeasure.org";
/** Units whose Waterbase or sandbox spelling is a valid UCUM code as written. */
const UCUM_UNITS = new Set(["mg/L", "ug/L", "Cel", "%", "mS/cm", "uS/cm", "mg{P}/L", "mg{N}/L", "mg{NO3}/L", "mg{NH4}/L", "mg{NO2}/L"]);
const COMPARATORS = new Set(["<", "<=", ">=", ">"]);

type Record_ = Schema<"MeasurementRecord">;
type Measurements = Schema<"SiteMeasurementsResponse">;

export interface FhirPlace {
  id: string;
  name: string;
  latitude: number | null;
  longitude: number | null;
}

type Json = { [key: string]: unknown };

const safeId = (value: string): string => value.replace(/[^A-Za-z0-9.-]/g, "-").slice(0, 60) || "x";

function periodOf(r: Record_): Json {
  const start = r.period_start ?? undefined;
  const end = r.period_end ?? undefined;
  if (start && end && start !== end) return { effectivePeriod: { start, end } };
  const single = start ?? end;
  if (single) return { effectiveDateTime: single };
  if (r.year) return { effectiveDateTime: r.month ? `${r.year}-${String(r.month).padStart(2, "0")}` : String(r.year) };
  return {};
}

function noteOf(r: Record_): string {
  const parts: string[] = [];
  if (r.statistic) parts.push(`Statistic: ${r.statistic}`);
  if (r.n != null) parts.push(`n=${r.n}`);
  if (r.min != null && r.max != null) parts.push(`observed range ${r.min} to ${r.max}`);
  if (r.n_below_loq) parts.push(`${r.n_below_loq} below the limit of quantification (not in the value)`);
  parts.push(`Reference check: ${r.status}`);
  if (r.limit != null) parts.push(`reference value ${r.limit} ${r.limit_unit ?? r.unit}${r.limit_basis ? ` (${r.limit_basis})` : ""}`);
  parts.push("Reference values are screening aids, not legal limits.");
  return parts.join("; ");
}

/** The Bundle for the records of one site; records without a numeric value are left out (never invented). */
export function measurementsBundle(d: Measurements, place: FhirPlace | null, now: Date = new Date(), uuid: () => string = () => crypto.randomUUID()): Json {
  const locationUrl = `urn:uuid:${uuid()}`;
  const locationId = `loc-${safeId(d.location_id)}`;
  const location: Json = {
    resourceType: "Location",
    id: locationId,
    identifier: [{ system: LOCATION_ID_SYSTEM, value: d.location_id }],
    name: place?.name ?? d.site?.name ?? d.location_id,
    mode: "instance",
    ...(place && place.latitude !== null && place.longitude !== null ? { position: { longitude: place.longitude, latitude: place.latitude } } : {}),
  };

  const observations: { url: string; resource: Json }[] = [];
  d.records.forEach((r, i) => {
    if (r.value == null) return;
    const quantity: Json = { value: r.value, unit: r.unit };
    if (r.comparator && COMPARATORS.has(r.comparator)) quantity.comparator = r.comparator;
    if (UCUM_UNITS.has(r.unit)) {
      quantity.system = UCUM;
      quantity.code = r.unit;
    }
    observations.push({
      url: `urn:uuid:${uuid()}`,
      resource: {
        resourceType: "Observation",
        id: `obs-${i + 1}`,
        meta: { tag: [{ system: ORIGIN_SYSTEM, code: r.origin }] },
        status: "final",
        code: { text: r.parameter },
        subject: { reference: locationUrl, display: String(location.name) },
        ...periodOf(r),
        valueQuantity: quantity,
        note: [{ text: noteOf(r) }],
      },
    });
  });

  const provenance: Json = {
    resourceType: "Provenance",
    id: "prov-1",
    target: observations.map((o) => ({ reference: o.url })),
    recorded: now.toISOString(),
    agent: [{ who: { display: "AquaLedger web app (software)" } }],
    entity: [{ role: "source", what: { display: d.attribution ?? d.origin } }],
  };

  return {
    resourceType: "Bundle",
    type: "collection",
    timestamp: now.toISOString(),
    meta: { tag: [{ system: ORIGIN_SYSTEM, code: d.origin }] },
    entry: [
      { fullUrl: locationUrl, resource: location },
      ...observations.map((o) => ({ fullUrl: o.url, resource: o.resource })),
      { fullUrl: `urn:uuid:${uuid()}`, resource: provenance },
    ],
  };
}

export function fhirFilename(locationId: string): string {
  return `measurements-${safeId(locationId)}-fhir.json`;
}
