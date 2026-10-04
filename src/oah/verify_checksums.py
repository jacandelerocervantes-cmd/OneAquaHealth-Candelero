"""Verify immutable official reference inputs."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator

from oah.paths import reference_path


def _entries() -> Iterator[tuple[str, str]]:
    for line in reference_path("CHECKSUMS.sha256").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        digest, filename = line.split(maxsplit=1)
        yield digest.lower(), filename.strip()


def _sha256(filename: str) -> str:
    digest = hashlib.sha256()
    with reference_path(filename).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify() -> list[str]:
    """Return validation errors, or an empty list when every hash matches."""
    errors: list[str] = []
    listed: set[str] = set()
    for expected, filename in _entries():
        listed.add(filename)
        try:
            actual = _sha256(filename)
        except FileNotFoundError:
            errors.append(f"missing: {filename}")
        else:
            if actual != expected:
                errors.append(f"hash mismatch: {filename}")
    unexpected = sorted(
        file.name
        for file in reference_path().iterdir()
        if file.is_file() and file.name != "CHECKSUMS.sha256" and file.name not in listed
    )
    errors.extend(f"unlisted: {filename}" for filename in unexpected)
    return errors


def main() -> None:
    errors = verify()
    if errors:
        raise SystemExit("Reference verification failed:\n" + "\n".join(errors))
    print("Official reference checksums verified.")
