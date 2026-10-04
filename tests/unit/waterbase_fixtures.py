"""Tiny synthetic stand-ins for the EEA Waterbase archive (no network, no real data).

They mimic the real layout verified on 2026-10-02: an outer ZIP with a top-level folder holding
``WISE6_DisaggregatedData-csv.zip`` and ``WISE6_SpatialObjects_DerivedData-csv.zip``; CSVs with a UTF-8 BOM and CRLF
line ends; the real column names; ``EL`` as the Greek country code; matrices W and W-DIS; the below-LOQ flag; the
observation-status letters; unit labels with a species basis (``mg{NO3}/L``). The values are invented for tests and
are labelled as such: nothing here is a measurement.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

from oah.waterbase.build import build_store, zip_lines

FOLDER = "eea_t_waterbase-water-quality-icm-2026_p_1900-2025_v01_r00"
BOM = "﻿"
HEADER = [
    "countryCode", "monitoringSiteIdentifier", "monitoringSiteIdentifierScheme", "parameterWaterBodyCategory",
    "observedPropertyDeterminandCode", "observedPropertyDeterminandLabel", "procedureAnalysedMatrix", "resultUom",
    "phenomenonTimeSamplingDate", "sampleIdentifier", "resultObservedValue", "resultQualityObservedValueBelowLOQ",
    "procedureLOQValue", "parameterSampleDepth", "parameterSedimentDepthSampled", "parameterSpecies", "resultMoisture",
    "resultFat", "resultExtractableLipid", "resultLipid", "resultObservationStatus", "Remarks", "metadata_versionId",
    "metadata_beginLifeSpanVersion", "metadata_statusCode", "metadata_observationStatus", "metadata_statements", "UID",
]
SPATIAL_HEADER = [
    "countryCode", "thematicIdIdentifier", "thematicIdIdentifierScheme", "monitoringSiteIdentifier",
    "monitoringSiteIdentifierScheme", "monitoringSiteName", "waterBodyIdentifier", "waterBodyIdentifierScheme",
    "waterBodyName", "specialisedZoneType", "naturalAWBHMWB", "reservoir", "surfaceWaterBodyTypeCode",
    "subUnitIdentifier", "subUnitIdentifierScheme", "subUnitName", "rbdIdentifier", "rbdIdentifierScheme", "rbdName",
    "confidentialityStatus", "lat", "lon",
]

NITRATE = ("CAS_14797-55-8", "Nitrate", "mg{NO3}/L")
NITRITE = ("CAS_14797-65-0", "Nitrite", "mg{NO2}/L")
AMMONIUM = ("CAS_14798-03-9", "Ammonium", "mg{NH4}/L")
TOTAL_P = ("CAS_7723-14-0", "Total phosphorus", "mg{P}/L")
PHOSPHATE = ("CAS_14265-44-2", "Phosphate", "mg{P}/L")
OXYGEN = ("EEA_3132-01-2", "Dissolved oxygen", "mg/L")
SATURATION = ("EEA_3131-01-9", "Oxygen saturation", "%")
TEMPERATURE = ("EEA_3121-01-5", "Water temperature", "Cel")
PH = ("EEA_3152-01-0", "pH", "[pH]")
LEAD = ("CAS_7439-92-1", "Lead and its compounds", "ug/L")
CADMIUM = ("CAS_7440-43-9", "Cadmium and its compounds", "ug/L")
CHLORIDE = ("CAS_16887-00-6", "Chloride", "mg/L")
ALACHLOR = ("CAS_15972-60-8", "Alachlor", "ug/L")

_counter = [0]


def obs(
    determinand: tuple[str, str, str] = NITRATE,
    value: str = "1.0",
    *,
    country: str = "IT",
    site: str = "IT01-001025",
    category: str = "RW",
    matrix: str = "W",
    date: str = "20150312",
    below: str = "0",
    status: str = "",
    reliability: str = "A",
    statements: str = "",
    uom: str | None = None,
) -> list[str]:
    """One disaggregated row (28 columns, like the real table)."""
    _counter[0] += 1
    code, label, unit = determinand
    return [
        country, site, "eionetMonitoringSiteCode", category, code, label, matrix, unit if uom is None else uom, date,
        "NA", value, below, "", "", "", "", "", "", "", "", status, "", "http://example.invalid/synthetic",
        "2015-11-30 00:00:00.000", "experimental", reliability, statements, str(_counter[0]),
    ]


def spatial(
    country: str, site: str, name: str, zone: str, water_body: str, lat: str, lon: str, confidentiality: str = "F"
) -> list[str]:
    row = [""] * len(SPATIAL_HEADER)
    values = {
        "countryCode": country, "thematicIdIdentifier": site, "monitoringSiteIdentifier": site,
        "monitoringSiteIdentifierScheme": "eionetMonitoringSiteCode", "monitoringSiteName": name,
        "waterBodyIdentifier": f"WB-{site}" if water_body else "", "waterBodyName": water_body,
        "specialisedZoneType": zone, "confidentialityStatus": confidentiality, "lat": lat, "lon": lon,
    }
    for key, value in values.items():
        row[SPATIAL_HEADER.index(key)] = value
    return row


def _csv_bytes(header: list[str], rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    return (BOM + buffer.getvalue()).encode("utf-8")


def standard_rows() -> list[list[str]]:
    """The invented slice: kept and dropped rows of every kind the build must handle."""
    _counter[0] = 0  # the same rows (UIDs included) every time, so archives are byte-comparable
    return [
        # Italian river: nitrate, two samples in 2015 (one lower-reliability), one in 2008 (before the minimum year)
        obs(NITRATE, "1.0"),
        obs(NITRATE, "3.0", reliability="U", date="20150901"),
        obs(NITRATE, "9.0", date="20080101"),
        # total phosphorus 0.04 and 0.08 mg{P}/L -> mean 0.06 as P; the Italian limit is 0.100 as P (compared as PO4)
        obs(TOTAL_P, "0.04"),
        obs(TOTAL_P, "0.08", date="20150601"),
        obs(PHOSPHATE, "0.02"),
        obs(OXYGEN, "9.0"),
        obs(SATURATION, "95"),
        obs(TEMPERATURE, "14.0"),
        obs(PH, "7.5"),
        obs(PH, "8.0", date="20150601"),
        obs(LEAD, "0.5", matrix="W-DIS"),
        obs(LEAD, "2.5", matrix="W-DIS", date="20150601"),
        obs(LEAD, "4.0", matrix="W"),  # whole water: listed, never compared with the dissolved limit
        obs(CADMIUM, "0.1", matrix="W-DIS"),
        obs(CHLORIDE, "12.0"),
        # a record whose quoted statement spans two lines; the second line starts like a record of another country
        obs(NITRATE, "2.0", date="20160101", statements="QC_NOTE: first line\r\nIT,not-a-record,continuation"),
        # Italian lake
        obs(NITRATE, "4.0", site="IT02-LAKE1", category="LW"),
        # Italian site that has no spatial row
        obs(NITRATE, "1.5", site="IT99-NOSPATIAL"),
        # Greek river (country code EL), no coordinates in the spatial table
        obs(OXYGEN, "5.0", country="EL", site="EL000123"),
        obs(OXYGEN, "5.4", country="EL", site="EL000123", date="20150601", reliability="V"),
        obs(NITRATE, "0.5", country="EL", site="EL000123"),
        # Greek ammonium: one quantified value and two below the limit of quantification (the value column holds
        # the limit, which must never be used as a measurement)
        obs(AMMONIUM, "0.05", country="EL", site="EL000123"),
        obs(AMMONIUM, "0.01", country="EL", site="EL000123", below="1", date="20150401"),
        obs(AMMONIUM, "0.01", country="EL", site="EL000123", below="1", date="20150501"),
        # a year with only below-LOQ values
        obs(NITRITE, "0.002", country="EL", site="EL000123", below="1", date="20170101"),
        # Norwegian river whose nitrate is reported as N (a different basis than the project's NO3)
        obs(NITRATE, "0.4", country="NO", site="NO0001", uom="mg{N}/L"),
        obs(NITRATE, "0.6", country="NO", site="NO0001", uom="mg{N}/L", date="20150601"),
        # ---- everything below must be dropped ----
        obs(NITRATE, "1.0", country="EL", site="EL-GW1", category="GW"),  # groundwater
        obs(NITRATE, "1.0", country="IT", site="IT-COAST", category="CW"),  # coastal
        obs(NITRATE, "1.0", country="DE", site="DE0001"),  # another country
        obs(NITRATE, "1.0", matrix="SED"),  # another matrix
        obs(ALACHLOR, "0.1"),  # a determinand outside the list
        obs(NITRATE, "", status="L"),  # missing value, not collected
        obs(NITRATE, "7.0", status="M"),  # missing value status even with a number
        obs(NITRATE, "NA"),  # not numeric
        obs(NITRATE, "1.0", uom=""),  # no unit
        obs(NITRATE, "nan"),  # not finite
        obs(NITRATE, "1.0", date="not-a-date"),
    ]


def standard_spatial() -> list[list[str]]:
    return [
        spatial("IT", "IT01-001025", "PO - REVELLO", "riverWaterBody", "PO", "44.65", "7.38"),
        spatial("IT", "IT02-LAKE1", "UNKNOWN", "lakeWaterBody", "LAGO TEST", "45.9", "8.6"),
        spatial("EL", "EL000123", "ALMYROS WELL FIELD", "riverWaterBody", "TEST BODY", "", "", "N"),
        spatial("NO", "NO0001", "Testelva", "riverWaterBody", "Testelva nedre", "60.1", "10.2"),
        spatial("EL", "", "", "groundWaterBody", "ALMYROS", "", ""),  # a water body row: no site identifier
    ]


def make_archive(
    path: Path, rows: list[list[str]] | None = None, spatial_rows: list[list[str]] | None = None
) -> Path:
    """An outer stored ZIP with a top-level folder and the two inner deflate ZIPs."""
    disaggregated = io.BytesIO()
    with zipfile.ZipFile(disaggregated, "w", zipfile.ZIP_DEFLATED) as inner:
        inner.writestr("Waterbase_v2025_1_T_WISE6_DisaggregatedData.csv", _csv_bytes(HEADER, standard_rows() if rows is None else rows))
    spatial_zip = io.BytesIO()
    with zipfile.ZipFile(spatial_zip, "w", zipfile.ZIP_DEFLATED) as inner:
        inner.writestr(
            "Waterbase_v2025_1_S_WISE6_SpatialObject_DerivedData.csv",
            _csv_bytes(SPATIAL_HEADER, standard_spatial() if spatial_rows is None else spatial_rows),
        )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as outer:
        outer.writestr(f"{FOLDER}/README.md", "synthetic test archive")
        outer.writestr(f"{FOLDER}/WISE6_DisaggregatedData-csv.zip", disaggregated.getvalue())
        outer.writestr(f"{FOLDER}/WISE6_SpatialObjects_DerivedData-csv.zip", spatial_zip.getvalue())
    return path


def disaggregated_lines(rows: list[list[str]] | None = None) -> list[bytes]:
    return _csv_bytes(HEADER, standard_rows() if rows is None else rows).splitlines(keepends=True)


def build_fixture_store(
    directory: Path,
    rows: list[list[str]] | None = None,
    spatial_rows: list[list[str]] | None = None,
    name: str = "store.sqlite",
    build_date: str = "2026-10-02T00:00:00Z",
) -> Path:
    """Build a store from the synthetic archive and return its path."""
    archive = make_archive(directory / "archive.zip", rows, spatial_rows)
    target = directory / name
    build_store(
        archive, target, directory / "work", stream_factory=zip_lines, build_date=build_date
    )
    return target
