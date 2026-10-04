"""Guard against hard-coded absolute paths outside the central path module."""

from __future__ import annotations

import re

from oah.paths import repo_path


WINDOWS_ABSOLUTE = re.compile(r"(?i)(?<![a-z0-9])[a-z]:[\\/]")
POSIX_ABSOLUTE = re.compile(r"(?<!:)/(?:Users|home|tmp|var|opt)/")
USER_MACHINE_MARKERS = re.compile(r"(?i)\b(?:onedrive|anton)\b|os\.getcwd\(")


def _has_nonportable_path(content: str) -> bool:
    return bool(
        WINDOWS_ABSOLUTE.search(content)
        or POSIX_ABSOLUTE.search(content)
        or USER_MACHINE_MARKERS.search(content)
    )


def test_windows_drive_pattern_avoids_false_positive_and_detects_path() -> None:
    assert not _has_nonportable_path("Reference verification failed:\\n")
    windows_path = "C" + ":" + "\\" + "Users" + "\\" + "x"
    assert _has_nonportable_path(windows_path)
    assert _has_nonportable_path("One" + "Drive")


def test_only_paths_module_may_construct_project_paths() -> None:
    violations: list[str] = []
    roots = ("src", "tests", "scripts", "docs")
    files = [file for root in roots for file in repo_path(root).rglob("*") if file.is_file()]
    files.extend(repo_path(name) for name in ("AGENTS.md", "README.md", ".env.example"))
    for file in files:
        if file.name in {"paths.py", "test_no_absolute_paths.py"}:
            continue
        try:
            content = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if _has_nonportable_path(content):
            violations.append(str(file))
    assert not violations, f"Non-portable path or machine marker: {violations}"
