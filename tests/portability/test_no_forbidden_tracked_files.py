"""Policy guard: third-party material with unresolved licensing must never be tracked by git.

The implementation-guide archive and its extraction, the reference archives and the organisers' slides stay
on a developer's disk only (SOURCES.yaml, docs/third_party_dependencies.md). The test reads the list of
tracked files, so it also protects a repository created from scratch. It is skipped outside a git checkout.
"""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from oah.paths import REPO_ROOT

FORBIDDEN = (
    re.compile(r"^ig/oah/"),
    re.compile(r"^reference/.*\.(zip|pdf)$", re.IGNORECASE),
    re.compile(r"^OneAquaHealth_hackathon_session_.*\.pdf$", re.IGNORECASE),
    re.compile(r"(^|/)\.env$"),
    re.compile(r"(^|/)credentials?\.json$", re.IGNORECASE),
)


def _tracked_files() -> list[str]:
    if shutil.which("git") is None or not (REPO_ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    result = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    return result.stdout.splitlines()


def test_no_unlicensed_or_secret_file_is_tracked():
    offenders = [name for name in _tracked_files() if any(pattern.search(name) for pattern in FORBIDDEN)]
    assert offenders == [], f"these files must stay out of git (see docs/third_party_dependencies.md): {offenders}"
