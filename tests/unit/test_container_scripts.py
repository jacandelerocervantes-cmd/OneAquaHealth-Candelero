"""The two scripts the image runs: the runtime requirement derivation and the container health probe."""

from __future__ import annotations

import ast
import importlib
import re
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.metadata import packages_distributions
from pathlib import Path
from types import ModuleType

import pytest

from oah.paths import repo_path, source_path


def _load(name: str):
    scripts_dir = str(repo_path("scripts"))
    sys.path.insert(0, scripts_dir)
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(scripts_dir)


@pytest.fixture()
def requirements() -> Iterator[ModuleType]:
    module = _load("runtime_requirements")
    yield module
    sys.modules.pop("runtime_requirements", None)


@pytest.fixture()
def probe() -> Iterator[ModuleType]:
    module = _load("container_healthcheck")
    yield module
    sys.modules.pop("container_healthcheck", None)


def _real_runtime_text(requirements: ModuleType) -> str:
    lock = repo_path("requirements-lock.txt").read_text(encoding="utf-8")
    return requirements.runtime_lock(lock, repo_path("pyproject.toml").read_text(encoding="utf-8"))


def _pins(text: str) -> dict[str, str]:
    return {re.sub(r"[-_.]+", "-", m.group(1)).lower(): m.group(2) for m in re.finditer(r"^([A-Za-z0-9._-]+)==(\S+)", text, re.M)}


def test_the_runtime_set_is_a_strict_hash_pinned_subset_without_development_packages(requirements: ModuleType):
    runtime = _pins(_real_runtime_text(requirements))
    full = _pins(repo_path("requirements-lock.txt").read_text(encoding="utf-8"))
    assert runtime and set(runtime) < set(full)
    assert all(full[name] == version for name, version in runtime.items())
    assert not set(runtime) & {"pytest", "pytest-cov", "hypothesis", "ruff", "mypy", "types-pyyaml", "coverage"}
    for needed in ("uvicorn", "fastapi", "starlette", "pydantic", "anthropic", "httpx", "httpx2", "pyyaml", "numpy", "networkx", "tzdata"):
        assert needed in runtime, needed
    text = _real_runtime_text(requirements)
    blocks = re.split(r"^(?=[A-Za-z0-9._-]+==)", text, flags=re.M)[1:]
    assert all("--hash=sha256:" in block for block in blocks) and len(blocks) == len(runtime)


def test_every_third_party_package_imported_by_the_source_is_in_the_runtime_set(requirements: ModuleType):
    runtime = _pins(_real_runtime_text(requirements))
    owners = packages_distributions()
    imported: set[str] = set()
    for path in source_path().rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
    third_party = imported - set(sys.stdlib_module_names) - {"oah", "__future__"}
    assert {"fastapi", "anthropic", "numpy"} <= third_party
    for top in sorted(third_party):
        distributions = {re.sub(r"[-_.]+", "-", name).lower() for name in owners.get(top, [])}
        assert distributions & set(runtime), f"{top} is imported by src/oah but is not in the runtime requirements"


def test_the_runtime_set_follows_the_requirement_edges_and_refuses_leaks_and_gaps(requirements: ModuleType):
    pyproject = '[project]\ndependencies = ["alpha==1", "Beta_Pkg==2"]\n'
    lock = (
        "# header\n"
        "alpha==1 \\\n    --hash=sha256:aa\n    # via oneaquahealth (pyproject.toml)\n"
        "beta-pkg==2 \\\n    --hash=sha256:bb\n    # via oneaquahealth (pyproject.toml)\n"
        "child==3 \\\n    --hash=sha256:cc\n    # via\n    #   alpha\n    #   other\n"
        "devtool==4 \\\n    --hash=sha256:dd\n    # via oneaquahealth (pyproject.toml)\n"
    )
    assert set(_pins(requirements.runtime_lock(lock, pyproject))) == {"alpha", "beta-pkg", "child"}
    with pytest.raises(ValueError, match="without a pin"):
        requirements.runtime_lock(lock.replace("alpha==1", "gamma==1"), pyproject)
    leaking = lock + "ruff==1 \\\n    --hash=sha256:ee\n    # via alpha\n"
    with pytest.raises(ValueError, match="Development-only"):
        requirements.runtime_lock(leaking, pyproject)


def test_the_command_line_writes_a_file_with_lf_endings_and_reports_errors(requirements: ModuleType, tmp_path: Path, capsys):
    output = tmp_path / "runtime.txt"
    code = requirements.main(
        ["--lock", str(repo_path("requirements-lock.txt")), "--pyproject", str(repo_path("pyproject.toml")), "--output", str(output)]
    )
    assert code == 0 and b"\r" not in output.read_bytes() and "pinned packages" in capsys.readouterr().out
    broken = tmp_path / "pyproject.toml"
    broken.write_text('[project]\ndependencies = ["missing-pkg==1"]\n', encoding="utf-8")
    assert requirements.main(["--lock", str(repo_path("requirements-lock.txt")), "--pyproject", str(broken), "--output", str(output)]) == 1
    assert "without a pin" in capsys.readouterr().err


class _Handler(BaseHTTPRequestHandler):
    status = 200

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        code = self.status if self.path == "/health" else 404
        self.send_response(code)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, *args: object) -> None:
        return


def _serve(status: int) -> tuple[HTTPServer, int]:
    handler = type("Handler", (_Handler,), {"status": status})
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def test_the_probe_succeeds_on_health_200_and_fails_on_another_status_or_a_closed_port(probe: ModuleType, monkeypatch):
    server, port = _serve(200)
    try:
        monkeypatch.setenv("PORT", str(port))
        assert probe.main() == 0
    finally:
        server.shutdown()
        server.server_close()
    server, port = _serve(503)
    try:
        monkeypatch.setenv("PORT", str(port))
        assert probe.main() == 1
    finally:
        server.shutdown()
        server.server_close()
    monkeypatch.setenv("PORT", str(port))  # closed now
    assert probe.main() == 1
