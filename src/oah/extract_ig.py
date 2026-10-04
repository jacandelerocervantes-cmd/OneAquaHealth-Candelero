"""Extract selected implementation-guide assets only after checksum verification."""

from __future__ import annotations

from pathlib import PurePosixPath
from zipfile import ZipFile

from oah.paths import ig_path, reference_path
from oah.verify_checksums import verify


ARCHIVE_ROOT = PurePosixPath("oah-master")
EXTRACTED_DIRECTORIES = (
    ARCHIVE_ROOT / "input",
    ARCHIVE_ROOT / "models-src",
)
SUSHI_CONFIG = ARCHIVE_ROOT / "sushi-config.yaml"


def _should_extract(member: PurePosixPath) -> bool:
    return member == SUSHI_CONFIG or any(member.is_relative_to(prefix) for prefix in EXTRACTED_DIRECTORIES)


def extract() -> int:
    """Extract official IG inputs, models, and SUSHI configuration from the archive."""
    errors = verify()
    if errors:
        raise RuntimeError("Cannot extract IG from unverified reference: " + "; ".join(errors))

    extracted = 0
    with ZipFile(reference_path("oah-master.zip")) as archive:
        for info in archive.infolist():
            member = PurePosixPath(info.filename)
            if ".." in member.parts:
                raise RuntimeError(f"Unsafe archive member: {info.filename}")
            if info.is_dir() or not _should_extract(member):
                continue
            relative = member.relative_to(ARCHIVE_ROOT)
            target = ig_path(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as destination:
                while block := source.read(1024 * 1024):
                    destination.write(block)
            extracted += 1
    return extracted


def main() -> None:
    print(f"Extracted {extract()} IG input files.")
