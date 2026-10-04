"""Static checks of the deployment package: Dockerfile, .dockerignore, Cloud Run service file, workflows, runbook."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from oah.external.settings import parse_external_settings
from oah.paths import BATHING_SAMPLES_STORE_NAME, BATHING_WATER_STORE_NAME, WATERBASE_STORE_NAME, repo_path, source_path

PLACEHOLDERS = {"PROJECT_ID", "REGION", "REPOSITORY", "TAG", "VERCEL_ORIGIN", "CONTACT_URL"}
SECRET_NAMES = {"ANTHROPIC_API_KEY": "oah-anthropic-api-key", "OAH_API_KEY": "oah-api-key"}


def _service_text() -> str:
    return repo_path("deploy", "cloudrun.service.yaml").read_text(encoding="utf-8")


def _service() -> dict[str, Any]:
    loaded = yaml.safe_load(_service_text())
    assert isinstance(loaded, dict)
    return loaded


def _container() -> dict[str, Any]:
    containers = _service()["spec"]["template"]["spec"]["containers"]
    assert len(containers) == 1
    return containers[0]


def _scanned_files() -> list[Path]:
    files = [repo_path("Dockerfile"), repo_path(".dockerignore"), repo_path("docs", "deployment.md")]
    files += [path for path in repo_path("deploy").rglob("*") if path.is_file()]
    files += sorted(repo_path(".github", "workflows").glob("*.yml"))
    files += [repo_path("scripts", name) for name in ("stage_deploy_stores.py", "runtime_requirements.py", "container_healthcheck.py", "make_synthetic_stores.py")]
    return files


def test_the_service_file_parses_and_has_the_expected_shape():
    service = _service()
    assert service["apiVersion"] == "serving.knative.dev/v1" and service["kind"] == "Service"
    assert service["metadata"]["name"] == "oah-backend"
    assert _service()["metadata"]["annotations"]["run.googleapis.com/ingress"] == "all"


def test_the_service_runs_exactly_one_instance_with_a_timeout_that_covers_chat_and_translation():
    template = _service()["spec"]["template"]
    annotations = template["metadata"]["annotations"]
    assert annotations["autoscaling.knative.dev/minScale"] == "1" and annotations["autoscaling.knative.dev/maxScale"] == "1"
    assert template["spec"]["timeoutSeconds"] >= 90  # chat 45 s + translation 30 s + margin
    env = {entry["name"]: entry.get("value") for entry in _container()["env"]}
    chat, translation = float(env["OAH_CHAT_TIMEOUT_SECONDS"]), float(env["OAH_TRANSLATION_TIMEOUT_SECONDS"])
    external = parse_external_settings({name: value for name, value in env.items() if value is not None and "<" not in value})
    one_failed_call = external.timeout_seconds * (1 + external.max_retries) + 1.0  # attempts plus the back-offs
    # chat deadline + translation + a species step that reaches the breaker (search plus three failed dataset calls)
    assert template["spec"]["timeoutSeconds"] >= chat + translation + 4 * one_failed_call
    assert template["spec"]["containerConcurrency"] <= 40  # the server's thread pool


def test_the_placeholders_are_exactly_the_documented_set():
    assert set(re.findall(r"<([A-Z_]+)>", _service_text())) == PLACEHOLDERS
    runbook = repo_path("docs", "deployment.md").read_text(encoding="utf-8")
    for name in PLACEHOLDERS:
        assert f"<{name}>" in runbook


def test_the_two_secrets_are_references_by_name_and_no_other_variable_carries_a_secret():
    env = {entry["name"]: entry for entry in _container()["env"]}
    for variable, secret in SECRET_NAMES.items():
        entry = env[variable]
        assert "value" not in entry and entry["valueFrom"]["secretKeyRef"] == {"name": secret, "key": "latest"}
    for name, entry in env.items():
        if name not in SECRET_NAMES:
            assert "secretKeyRef" not in entry.get("valueFrom", {})
            assert not re.search(r"KEY|SECRET|TOKEN|PASSWORD", name), f"{name} looks like a credential"
    assert "OAH_INSECURE_NO_AUTH" not in env and "OAH_TRUSTED_PROXIES" not in env and "OAH_ENABLE_DOCS" not in env
    assert not {"OAH_WATERBASE_STORE", "OAH_BATHING_WATER_STORE", "OAH_BATHING_SAMPLES_STORE"} & set(env)  # the image sets them


def _known_names() -> set[str]:
    text = "".join(source_path(*parts).read_text(encoding="utf-8") for parts in (("config.py",), ("paths.py",), ("external", "settings.py")))
    return set(re.findall(r"\b(?:OAH_[A-Z0-9_]+|ANTHROPIC_API_KEY)\b", text))


def test_every_variable_set_in_the_service_file_and_the_dockerfile_is_read_by_the_application():
    known = _known_names()
    in_yaml = {entry["name"] for entry in _container()["env"]}
    dockerfile = repo_path("Dockerfile").read_text(encoding="utf-8")
    in_dockerfile = set(re.findall(r"^\s*(OAH_[A-Z0-9_]+)=", dockerfile, re.M))
    assert {"OAH_DATA_DIR", "OAH_WATERBASE_STORE", "OAH_BATHING_WATER_STORE", "OAH_BATHING_SAMPLES_STORE"} <= in_dockerfile
    for name in sorted((in_yaml | in_dockerfile) - {"PORT"}):
        assert name in known, f"{name} is set for the container but not read by config.py or paths.py"


def test_the_runbook_names_only_variables_the_application_reads():
    runbook = repo_path("docs", "deployment.md").read_text(encoding="utf-8")
    mentioned = set(re.findall(r"\bOAH_[A-Z0-9_]+\b", runbook))
    assert mentioned and mentioned <= _known_names() | {"OAH_SOURCES_ROOT"}


def test_the_service_file_sets_the_external_context_explicitly_with_a_placeholder_contact_page():
    env = {entry["name"]: entry.get("value") for entry in _container()["env"]}
    external = {name for name in env if name.startswith("OAH_EXTERNAL_")} | {"OAH_CONTACT_URL"} & set(env)
    assert external == {
        "OAH_EXTERNAL_ENABLED", "OAH_EXTERNAL_OPEN_METEO_ENABLED", "OAH_EXTERNAL_GLOFAS_ENABLED", "OAH_EXTERNAL_GBIF_ENABLED",
        "OAH_CONTACT_URL", "OAH_EXTERNAL_TIMEOUT_SECONDS", "OAH_EXTERNAL_CACHE_TTL_SECONDS", "OAH_EXTERNAL_CACHE_SIZE",
        "OAH_EXTERNAL_OPEN_METEO_PER_MINUTE", "OAH_EXTERNAL_OPEN_METEO_DAILY", "OAH_EXTERNAL_GBIF_PER_MINUTE", "OAH_EXTERNAL_GBIF_DAILY",
    }
    assert env["OAH_CONTACT_URL"] == "<CONTACT_URL>" and "@" not in _service_text().split("OAH_CONTACT_URL")[1].splitlines()[1]
    values = {name: value for name, value in env.items() if name in external and name != "OAH_CONTACT_URL"}
    settings = parse_external_settings({name: str(value) for name, value in values.items()})
    assert settings.enabled and settings.open_meteo_enabled and settings.glofas_enabled and settings.gbif_enabled
    # Every explicit budget is at or below the code default and nothing relies on the ceiling clamping a typo.
    from oah.external import settings as module

    assert settings.open_meteo_per_minute <= module.DEFAULT_OPEN_METEO_PER_MINUTE and settings.open_meteo_daily <= module.DEFAULT_OPEN_METEO_DAILY
    assert settings.gbif_per_minute <= module.DEFAULT_GBIF_PER_MINUTE and settings.gbif_daily <= module.DEFAULT_GBIF_DAILY
    assert str(settings.timeout_seconds).rstrip("0").rstrip(".") == values["OAH_EXTERNAL_TIMEOUT_SECONDS"]  # not clamped


def test_the_memory_limit_covers_three_baked_in_stores_with_headroom():
    memory = _container()["resources"]["limits"]["memory"]
    assert memory.endswith("Gi") and int(memory[:-2]) >= 2


def test_the_taxon_file_the_external_context_reads_ships_inside_the_copied_source_tree():
    assert repo_path("src", "oah", "external", "data", "gbif_taxa.json").is_file()
    assert "src" in _reincluded()


def test_the_image_store_paths_use_the_default_file_names_and_one_directory():
    dockerfile = repo_path("Dockerfile").read_text(encoding="utf-8")
    assert f"OAH_WATERBASE_STORE=/data/stores/{WATERBASE_STORE_NAME}" in dockerfile
    assert f"OAH_BATHING_WATER_STORE=/data/stores/{BATHING_WATER_STORE_NAME}" in dockerfile
    assert f"OAH_BATHING_SAMPLES_STORE=/data/stores/{BATHING_SAMPLES_STORE_NAME}" in dockerfile
    copy = next(line for line in dockerfile.splitlines() if line.startswith("COPY --from=stores"))
    assert WATERBASE_STORE_NAME in copy and BATHING_WATER_STORE_NAME in copy and BATHING_SAMPLES_STORE_NAME in copy and "manifest.json" in copy
    assert "--chmod=0444" in copy and copy.rstrip().endswith("/data/stores/")


def _dockerfile_instructions() -> list[str]:
    text = repo_path("Dockerfile").read_text(encoding="utf-8").replace("\\\r\n", " ").replace("\\\n", " ")
    return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]


def test_the_dockerfile_runs_one_worker_without_reload_as_an_unprivileged_user():
    instructions = _dockerfile_instructions()
    users = [line.split()[1] for line in instructions if line.startswith("USER ")]
    assert users and users[-1] not in ("root", "0")
    assert instructions[-1].startswith("CMD ")
    command = instructions[-1]
    assert "--workers 1" in command and "--reload" not in command and "exec uvicorn oah.api.app:app" in command
    assert "--no-proxy-headers" in command  # the application's own client_ip module decides what to believe
    assert not any(line.startswith("ADD ") for line in instructions)
    assert any(line.startswith("HEALTHCHECK ") for line in instructions)
    assert not re.search(r"--reload|pip install(?! --require-hashes)", "\n".join(instructions[:-1]).replace("python -m pip install --require-hashes", ""))


def _reincluded() -> list[str]:
    lines = [line.strip() for line in repo_path(".dockerignore").read_text(encoding="utf-8").splitlines()]
    return [line[1:] for line in lines if line.startswith("!")]


def _allowed(path: str, reincluded: list[str]) -> bool:
    return any(path == item or path.startswith(item + "/") for item in reincluded)


def test_the_base_image_is_pinned_by_digest_and_both_stages_use_it():
    dockerfile = repo_path("Dockerfile").read_text(encoding="utf-8")
    default = re.search(r"^ARG PYTHON_IMAGE=(\S+)$", dockerfile, re.M)
    assert default, "the ARG default must hold the base image"
    assert re.fullmatch(r"python:3\.12-slim-bookworm@sha256:[0-9a-f]{64}", default.group(1)), default.group(1)
    froms = [line for line in _dockerfile_instructions() if line.startswith("FROM ")]
    assert len(froms) == 2 and all(line.split()[1] == "${PYTHON_IMAGE}" for line in froms)  # no stage names its own tag
    assert "python:3.12-slim-bookworm" in "\n".join(line for line in dockerfile.splitlines() if line.startswith("#"))  # tag kept for humans


def test_the_dependency_audit_ignore_list_gives_a_reason_for_every_entry():
    path = repo_path("security", "pip-audit-ignore.txt")
    entries = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.strip().startswith("#")]
    for entry in entries:  # format: ID | reason | review-by YYYY-MM-DD
        parts = [part.strip() for part in entry.split("|")]
        assert len(parts) == 3 and parts[0] and parts[1], f"ignore entry without a reason: {entry!r}"
        assert re.fullmatch(r"review-by \d{4}-\d{2}-\d{2}", parts[2]), entry
    workflow = yaml.safe_load(repo_path(".github", "workflows", "ci.yml").read_text(encoding="utf-8"))
    audit = "\n".join(str(step.get("run", "")) for step in workflow["jobs"]["dependency-audit"]["steps"])
    assert "pip_audit" in audit and "requirements-lock.txt" in audit and "pip-audit-ignore.txt" in audit
    assert "continue-on-error" not in yaml.safe_dump(workflow["jobs"]["dependency-audit"])  # blocking, as documented


def test_the_dockerfile_copy_sources_exist_and_are_reincluded_by_the_dockerignore():
    sources: list[str] = []
    for line in _dockerfile_instructions():
        if line.startswith("COPY ") and "--from=" not in line:
            parts = [part for part in line.split()[1:] if not part.startswith("--")]
            sources += parts[:-1]
    assert {"pyproject.toml", "requirements-lock.txt", "src", "scripts/runtime_requirements.py", "scripts/container_healthcheck.py"} <= set(sources)
    reincluded = _reincluded()
    for source in sources:
        assert repo_path(*source.split("/")).exists(), source
        assert _allowed(source, reincluded), f"{source} is copied but not re-included in .dockerignore"
    assert set(reincluded) == {"pyproject.toml", "requirements-lock.txt", "src", "scripts/runtime_requirements.py", "scripts/container_healthcheck.py"}


def test_the_dockerignore_is_an_allow_list_that_keeps_secrets_data_and_development_trees_out():
    lines = [line.strip() for line in repo_path(".dockerignore").read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    assert lines[0] == "*"
    reincluded = _reincluded()
    for excluded in (".env", ".env.local", ".git", ".github", "tests", "docs", "fixtures", "reference", "ig", "stack-ia-dev", "frontend", "node_modules", "data", "README.md"):
        assert not _allowed(excluded, reincluded), f"{excluded} must not reach the image"
    assert "**/.env" in lines and "**/.env.*" in lines  # also when nested inside the re-included src/
    assert "**/__pycache__" in lines


def test_no_secret_looking_value_personal_path_or_real_cloud_name_in_the_deployment_files():
    token = re.compile(r"[A-Za-z0-9]{32,}")
    patterns = {
        "anthropic key": re.compile(r"sk-ant"),
        "api key prefix": re.compile(r"\b(?:AIza|ghp_|gho_|xox[bp]-|AKIA)[A-Za-z0-9_-]{10,}"),
        "private key": re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
        "windows path": re.compile(r"\b[A-Za-z]:[\\/](?:Users|dev|Windows|Program)", re.I),
        "unix home": re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+"),
        "personal name": re.compile(r"ant" r"on|candelero|gmail|@hotmail|@outlook", re.I),
        "bucket": re.compile(r"\bgs://(?!<)[A-Za-z0-9._-]+"),
        "service account of a real project": re.compile(r"@(?!<PROJECT_ID>)[a-z][a-z0-9-]{4,}\.iam\.gserviceaccount\.com"),
        "registry path of a real project": re.compile(r"-docker\.pkg\.dev/(?!<PROJECT_ID>)[A-Za-z0-9-]+"),
        "project resource": re.compile(r"projects/(?!<PROJECT_ID>)\d{6,}"),
        "vercel host": re.compile(r"https://[a-z0-9-]+\.vercel\.app"),
        "inline secret assignment": re.compile(r"(?:API_KEY|SECRET|TOKEN|PASSWORD)\s*[:=]\s*[\"']?[A-Za-z0-9+/_-]{12,}", re.I),
    }
    for path in _scanned_files():
        assert path.is_file(), path
        # A pinned image digest (sha256 plus 64 hex characters) is public, not a secret: remove it before scanning.
        text = re.sub(r"@sha256:[0-9a-f]{64}\b", "@sha256:<digest>", path.read_text(encoding="utf-8"))
        for label, pattern in patterns.items():
            match = pattern.search(text)
            assert match is None, f"{path.name}: {label}: {match.group(0) if match else ''}"
        for candidate in token.findall(text):
            if re.search(r"[A-Za-z]", candidate) and re.search(r"\d", candidate):
                pytest.fail(f"{path.name}: long token-like string {candidate[:12]}...")


def test_the_workflows_are_valid_yaml_read_only_and_use_no_secrets_or_cloud_credentials():
    workflows = sorted(repo_path(".github", "workflows").glob("*.yml"))
    assert {path.name for path in workflows} >= {"ci.yml", "deploy-checks.yml"}
    for path in workflows:
        text = path.read_text(encoding="utf-8")
        document = yaml.safe_load(text)
        assert isinstance(document, dict) and document["jobs"], path.name
        assert document["permissions"] == {"contents": "read"}
        assert "secrets." not in text and "id-token" not in text and "gcloud" not in text and "docker push" not in text
    deploy = yaml.safe_load((repo_path(".github", "workflows", "deploy-checks.yml")).read_text(encoding="utf-8"))
    steps = "\n".join(str(step.get("run", "")) for job in deploy["jobs"].values() for step in job["steps"])
    assert "export_openapi.py --check" in steps and "--build-context stores=" in steps and "--push" not in steps
    assert "make_synthetic_stores.py" in steps and "test_deploy_files.py" in steps


def test_the_runbook_states_what_was_not_verified():
    runbook = repo_path("docs", "deployment.md").read_text(encoding="utf-8")
    assert "What was NOT verified" in runbook
    for heading in ("Rollback", "Single instance", "Security checklist", "OAH_TRUSTED_PROXIES"):
        assert heading in runbook
