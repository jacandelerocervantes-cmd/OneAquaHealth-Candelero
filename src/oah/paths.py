"""The sole project-path constructor.

All project locations derive from the nearest ancestor containing pyproject.toml,
never from the process working directory.
"""

from __future__ import annotations

from pathlib import Path
from os import getenv


def _find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise RuntimeError("Cannot locate OneAquaHealth repository marker (pyproject.toml).")


REPO_ROOT = _find_repo_root(Path(__file__).resolve())


def repo_path(*parts: str) -> Path:
    """Return a path anchored at the repository root."""
    return REPO_ROOT.joinpath(*parts)


def source_path(*parts: str) -> Path:
    """Return a source-package path."""
    return repo_path("src", "oah", *parts)


def reference_path(*parts: str) -> Path:
    """Return a read-only official-reference path."""
    return repo_path("reference", *parts)


def fixture_path(*parts: str) -> Path:
    """Return a versioned fixture path."""
    return repo_path("fixtures", *parts)


def fixtures_real_path(*parts: str) -> Path:
    """Return a path for captured real sandbox fixtures."""
    return fixture_path("real", *parts)


def ig_path(*parts: str) -> Path:
    """Return a path inside the extracted implementation guide."""
    return repo_path("ig", "oah", *parts)


def openapi_path() -> Path:
    """Return the committed OpenAPI schema file (``scripts/export_openapi.py`` writes it)."""
    return repo_path("docs", "openapi.json")


def external_path(value: str, variable: str) -> Path:
    """Validate an externally configured path without anchoring it to this repo."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise RuntimeError(f"{variable} must be an absolute external path.")
    return path


def default_data_dir() -> Path:
    """Return a user cache location outside the synchronized project directory."""
    local_app_data = getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data).joinpath("OneAquaHealth")
    return Path.home().joinpath(".cache", "oneaquahealth")


def sandbox_snapshot_path(resource_type: str) -> Path:
    """Return an external sandbox snapshot path."""
    from oah.config import data_dir
    return data_dir().joinpath("sandbox", f"{resource_type}.json")

def qc_report_path(name: str) -> Path:
    """Return an external QC report path."""
    from oah.config import data_dir
    return data_dir().joinpath("reports", name)


def export_path(name: str) -> Path:
    """Return an external generated-FHIR export path."""
    from oah.config import data_dir

    return data_dir().joinpath("exports", name)

def tools_dir() -> Path:
    """Return the externally configured OAH tool directory."""
    from os import getenv
    configured = getenv("OAH_TOOLS_DIR")
    return external_path(configured, "OAH_TOOLS_DIR") if configured else default_data_dir().joinpath("tools")

def ig_build_path(*parts: str) -> Path:
    """Return an external implementation-guide build path."""
    from oah.config import data_dir
    return data_dir().joinpath("ig-build", *parts)


def llm_audit_path(name: str = "llm_calls.jsonl") -> Path:
    """Return the external append-only audit log of requests sent to the LLM provider."""
    from oah.config import data_dir
    return data_dir().joinpath("audit", name)


def review_db_path(name: str = "oah_review.db") -> Path:
    """Return an external human-review database path."""
    from oah.config import data_dir
    return data_dir().joinpath("review", name)


WATERBASE_ARCHIVE_NAME = "eea_t_waterbase-water-quality-icm-2026_p_1900-2025_v01_r00.zip"
WATERBASE_STORE_NAME = "waterbase_icm_2026.sqlite"


def waterbase_archive_path() -> Path:
    """Return the external EEA Waterbase ICM 2026 archive (downloaded outside the repository)."""
    from oah.config import data_dir
    return data_dir().joinpath("data", "waterbase", "2026", WATERBASE_ARCHIVE_NAME)


def waterbase_store_path() -> Path:
    """Return the external Waterbase SQLite store: ``OAH_WATERBASE_STORE`` when set, else under the data directory."""
    from oah.config import data_dir, load_settings
    configured = load_settings().waterbase_store
    return configured if configured is not None else data_dir().joinpath("waterbase", WATERBASE_STORE_NAME)


def waterbase_work_dir() -> Path:
    """Return the external scratch directory the store build copies the inner archives into."""
    from oah.config import data_dir
    return data_dir().joinpath("waterbase", "work")


BATHING_WATER_ARCHIVE_NAME = "eea_t_bathing-water-status_p_1990-2025_v01_r00.zip"
BATHING_WATER_STORE_NAME = "bathing_water_2025.sqlite"


def bathing_water_archive_path() -> Path:
    """Return the external EEA bathing-water status 2025 archive (downloaded outside the repository)."""
    from oah.config import data_dir
    return data_dir().joinpath("data", "bathing_water", "2025", BATHING_WATER_ARCHIVE_NAME)


def bathing_water_store_path() -> Path:
    """Return the external bathing-water SQLite store: ``OAH_BATHING_WATER_STORE`` when set, else under the data directory."""
    from oah.config import data_dir, load_settings
    configured = load_settings().bathing_water_store
    return configured if configured is not None else data_dir().joinpath("bathing_water", BATHING_WATER_STORE_NAME)


def bathing_water_work_dir() -> Path:
    """Return the external scratch directory used only if the workbook inside the archive is compressed."""
    from oah.config import data_dir
    return data_dir().joinpath("bathing_water", "work")


BATHING_SAMPLES_STORE_NAME = "bathing_samples_discodata.sqlite"


def bathing_samples_store_path() -> Path:
    """Return the external bathing-water SAMPLES SQLite store: ``OAH_BATHING_SAMPLES_STORE`` when set, else under the data directory."""
    from oah.config import data_dir, load_settings
    configured = load_settings().bathing_samples_store
    return configured if configured is not None else data_dir().joinpath("bathing_samples", BATHING_SAMPLES_STORE_NAME)


def bathing_samples_work_dir() -> Path:
    """Return the external work directory of the samples build: one file per downloaded page, so an interrupted build can resume."""
    from oah.config import data_dir
    return data_dir().joinpath("bathing_samples", "work")


def deploy_stage_dir() -> Path:
    """Return the external staging directory that the container image build reads the prebuilt stores from."""
    from oah.config import data_dir
    return data_dir().joinpath("deploy_stage")


def sevenzip_executable() -> Path | None:
    """Locate 7-Zip: ``OAH_SEVENZIP_PATH``, then ``7z`` on the PATH, then the standard Windows install folder.

    Returns None when none exists; the caller reports it (the store build cannot read the 1.6 GB inner archive
    without 7-Zip, whose compression method Python's zipfile does not support).
    """
    from shutil import which
    from oah.config import load_settings
    configured = load_settings().sevenzip_path
    if configured is not None:
        return configured if configured.is_file() else None
    found = which("7z")
    if found:
        return Path(found)
    program_files = getenv("ProgramFiles")
    if program_files:
        candidate = Path(program_files).joinpath("7-Zip", "7z.exe")
        if candidate.is_file():
            return candidate
    return None

