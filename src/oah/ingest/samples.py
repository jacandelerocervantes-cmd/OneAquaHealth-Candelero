"""Read archived official `_samples` directly from the verified reference archive."""

from __future__ import annotations

from functools import lru_cache
from pathlib import PurePosixPath
from zipfile import ZipFile

from oah.paths import reference_path
from oah.verify_checksums import verify


ARCHIVE_ROOT = PurePosixPath("oah-master/_samples")


@lru_cache(maxsize=1)
def _ensure_verified() -> None:
    """Verify official inputs once per process before reading archived samples."""
    errors = verify()
    if errors:
        raise RuntimeError("Cannot read unverified reference: " + "; ".join(errors))


def _member_name(relative_name: str) -> str:
    relative = PurePosixPath(relative_name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Sample path must be relative to _samples and must not traverse parents.")
    return str(ARCHIVE_ROOT / relative)


def sample_names() -> tuple[str, ...]:
    """Return sample names from the verified archive without extracting them."""
    _ensure_verified()
    with ZipFile(reference_path("oah-master.zip")) as archive:
        return tuple(
            sorted(
                str(PurePosixPath(info.filename).relative_to(ARCHIVE_ROOT))
                for info in archive.infolist()
                if not info.is_dir() and PurePosixPath(info.filename).is_relative_to(ARCHIVE_ROOT)
            )
        )


def read_sample_bytes(relative_name: str) -> bytes:
    """Read one verified archived sample without writing it to the filesystem."""
    _ensure_verified()
    with ZipFile(reference_path("oah-master.zip")) as archive:
        return archive.read(_member_name(relative_name))
