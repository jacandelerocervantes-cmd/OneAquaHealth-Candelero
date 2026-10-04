"""Access to the EEA archive: streaming the inner CSV, copying members out of the zip, and the archive hash."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path


@contextmanager
def sevenzip_lines(sevenzip: Path, inner_zip: Path) -> Iterator[Iterator[bytes]]:
    """Stream the single CSV of an inner archive through ``7z e -so`` (Python's zipfile cannot read its method)."""
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            [str(sevenzip), "e", "-so", "-bd", str(inner_zip)],
            stdout=subprocess.PIPE, stderr=errors, bufsize=1 << 20,
        )
        assert process.stdout is not None
        try:
            yield iter(process.stdout)
        except BaseException:
            process.kill()
            raise
        finally:
            process.stdout.close()
            code = process.wait()
        if code != 0:
            errors.seek(0)
            tail = errors.read()[-400:].decode("utf-8", "replace")
            raise RuntimeError(f"7-Zip failed with exit code {code}: {tail}")


def zip_lines(inner_zip: Path) -> AbstractContextManager[Iterator[bytes]]:
    """Stream the single CSV of an inner archive with Python's zipfile (works for deflate; used for small inputs)."""

    @contextmanager
    def _open() -> Iterator[Iterator[bytes]]:
        with zipfile.ZipFile(inner_zip) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if len(names) != 1:
                raise RuntimeError(f"Expected one CSV in {inner_zip.name}, found {len(names)}.")
            with archive.open(names[0]) as stream:
                yield iter(stream)

    return _open()


def _find_member(archive: zipfile.ZipFile, basename: str) -> zipfile.ZipInfo:
    for info in archive.infolist():
        if info.filename.rsplit("/", 1)[-1] == basename:
            return info
    raise RuntimeError(f"The archive has no {basename}.")


def _copy_member(archive: zipfile.ZipFile, basename: str, destination: Path) -> Path:
    info = _find_member(archive, basename)
    target = destination / basename
    with archive.open(info) as source, open(target, "wb") as sink:
        shutil.copyfileobj(source, sink, 1 << 20)
    return target


def read_sha256_sidecar(archive: Path) -> str | None:
    """The hash published next to the archive (``<archive>.sha256``, first token), if the file exists."""
    sidecar = archive.with_name(archive.name + ".sha256")
    if not sidecar.is_file():
        return None
    parts = sidecar.read_text(encoding="utf-8").split()
    return parts[0].lower() if parts else None


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 24), b""):
            digest.update(chunk)
    return digest.hexdigest()
