"""Portability contract: project paths never depend on the working directory."""

from __future__ import annotations

import os
import subprocess
import sys

from oah.paths import REPO_ROOT


def test_repo_root_is_marker_anchored_from_another_directory(tmp_path) -> None:
    environment = os.environ | {"PYTHONPATH": str(REPO_ROOT / "src")}
    result = subprocess.run(
        [sys.executable, "-c", "from oah.paths import REPO_ROOT; print(REPO_ROOT)"],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == str(REPO_ROOT)
