"""Static guards: lint (ruff, rules from pyproject.toml) and type checking (mypy, config from pyproject.toml).

Pure unit tests cannot see a missing import in a script that is only run by hand
(scripts/build_ig.py once shipped without `import shutil`), a type error on a rarely used branch, or an
API that only exists on one supported Python version. These checks do.
"""

import subprocess
import sys

import pytest

from oah.paths import repo_path


def test_no_lint_findings() -> None:
    command = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "src",
        "scripts",
        "tests",
        "--no-cache",
        "--output-format",
        "concise",
    ]
    result = subprocess.run(command, cwd=repo_path(), capture_output=True, text=True)
    if "No module named ruff" in result.stderr:
        pytest.skip("ruff is not installed in this environment")
    assert result.returncode == 0, result.stdout + result.stderr


def test_no_type_errors() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--no-incremental"], cwd=repo_path(), capture_output=True, text=True
    )
    if "No module named mypy" in result.stderr:
        pytest.skip("mypy is not installed in this environment")
    assert result.returncode == 0, result.stdout + result.stderr
