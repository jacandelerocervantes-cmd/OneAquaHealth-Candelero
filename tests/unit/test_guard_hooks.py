"""The repository's guard hooks (hooks/*.sh), run the way Claude Code runs them.

Claude Code starts each hook with the repository as the working directory, writes the tool call as JSON on standard
input (``{"tool_name": ..., "tool_input": {...}}``) and treats exit code 2 as a block (standard error goes to the
agent) and any other code as "allowed" or as a non-blocking error. The wiring (which hook runs for which tool) is in
.claude/settings.json and is checked here too.

Safety: the hooks only READ the JSON text. Nothing below executes a guarded command; every "dangerous" string is data
for the hook's regular expressions. Public invocation of the Cloud Run service (the flag that allows unauthenticated
callers) is blocked on purpose: enabling it is a deliberate, manual maintainer step (docs/predeploy_checklist.md).

Fail-closed contract: a hook that cannot decide (jq missing, empty or malformed input) exits 2, never 127 or 5.
Coverage contract (.claude/settings.json): the three command hooks run for the Bash and the PowerShell tools; the
secrets hook also runs for Read, Edit, Write, NotebookEdit, Grep and Glob.

The tests need a WORKING ``bash`` and ``jq`` (the hooks parse the JSON with jq). The module looks for Git for Windows'
bash first, then ``bash`` from the PATH, and accepts a candidate only after a probe command ran and printed a marker.
The Windows WSL launcher stub (the ``bash.exe`` in the Windows system folder) is never accepted: without an installed
distribution it exits 1 for every command, which would otherwise look like "the hook let the command through". When no
working bash or no jq is found, every hook test is skipped with a reason naming what is missing. On the Ubuntu runners
of GitHub Actions both are preinstalled (see docs/predeploy_checklist.md).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from oah.paths import repo_path

DESTRUCTIVE = "hooks/block-destructive-bash.sh"
NETWORK = "hooks/block-network-exposure.sh"
SECRETS = "hooks/protect-secrets.sh"
BASH_HOOKS = (DESTRUCTIVE, NETWORK, SECRETS)

PROBE_MARKER = "oah-probe"
WSL_ERROR_TEXT = "WSL"


def _git_for_windows_candidates(which: Callable[[str], str | None], environ: Mapping[str, str]) -> list[str]:
    roots: list[Path] = []
    git = which("git")
    if git:
        roots.append(Path(git).parent.parent)  # <root>/cmd/git.exe or <root>/bin/git.exe
    for variable in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        if environ.get(variable):
            roots.append(Path(environ[variable]) / "Git")
    if environ.get("LOCALAPPDATA"):
        roots.append(Path(environ["LOCALAPPDATA"]) / "Programs" / "Git")
    candidates: list[str] = []
    for root in roots:
        candidates.extend(str(root / part / "bash.exe") for part in ("bin", "usr/bin"))
    return candidates


def _is_system_folder_stub(candidate: str, environ: Mapping[str, str]) -> bool:
    system = environ.get("SystemRoot") or environ.get("WINDIR")
    if not system:
        return False
    try:
        Path(candidate).resolve().relative_to(Path(system).resolve())
    except (ValueError, OSError):
        return False
    return True


def _probe(candidate: str, run: Callable[..., subprocess.CompletedProcess[str]]) -> bool:
    try:
        result = run([candidate, "-c", f"echo {PROBE_MARKER}"], capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and PROBE_MARKER in (result.stdout or "")


def find_working_bash(
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    environ: Mapping[str, str] = os.environ,
    platform: str = sys.platform,
) -> tuple[str | None, str]:
    """``(path, "")`` of the first bash that passes the probe, or ``(None, reason)`` when bash or jq is unusable."""
    candidates: list[str] = _git_for_windows_candidates(which, environ) if platform == "win32" else []
    on_path = which("bash")
    if on_path:
        candidates.append(on_path)
    rejected: list[str] = []
    for candidate in dict.fromkeys(candidates):
        if platform == "win32" and not Path(candidate).is_file():
            continue
        if _is_system_folder_stub(candidate, environ):
            rejected.append("a bash in the Windows system folder (the WSL launcher does not count)")
            continue
        if _probe(candidate, run):
            if which("jq") is None:
                return None, "jq was not found on the PATH (the hooks parse their input with jq)"
            return candidate, ""
        rejected.append("a bash that failed the probe command (for example the WSL launcher without a distribution)")
    detail = f"; rejected: {'; '.join(rejected)}" if rejected else ""
    return None, f"no working bash was found (tried Git for Windows locations and the PATH{detail})"


BASH, SKIP_REASON = find_working_bash()


@pytest.fixture(autouse=True)
def _require_working_runtime(request: pytest.FixtureRequest) -> None:
    if BASH is None and not request.node.name.startswith("test_discovery"):
        pytest.skip(f"guard hook tests need a working bash and jq: {SKIP_REASON}")


def run_hook(script: str, payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    """Run one hook with the repository as the working directory and the JSON payload on standard input."""
    return run_hook_text(script, json.dumps(payload))


def run_hook_text(
    script: str, text: str, env: Mapping[str, str] | None = None, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Run one hook with raw text on standard input (also for payloads that are not valid JSON)."""
    assert BASH is not None
    result = subprocess.run(
        [BASH, script],
        input=text,
        cwd=cwd or repo_path(),
        env=None if env is None else dict(env),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    if result.returncode in (126, 127) or WSL_ERROR_TEXT in result.stderr:
        pytest.fail(f"the bash interpreter is not usable (exit {result.returncode}), not a hook decision: {result.stderr}")
    return result


def bash_payload(command: str) -> dict[str, object]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def file_payload(tool: str, path: str) -> dict[str, object]:
    return {"tool_name": tool, "tool_input": {"file_path": path}}


def blocking_hooks(payload: dict[str, object], scripts: tuple[str, ...]) -> list[str]:
    return [script for script in scripts if run_hook(script, payload).returncode == 2]


def test_hook_scripts_exist() -> None:
    for script in BASH_HOOKS:
        assert repo_path(script).is_file()


def _wiring() -> dict[str, list[str]]:
    settings = json.loads(repo_path(".claude", "settings.json").read_text(encoding="utf-8"))
    return {entry["matcher"]: [hook["command"] for hook in entry["hooks"]] for entry in settings["hooks"]["PreToolUse"]}


def hook_command(script: str) -> str:
    """The command string of .claude/settings.json: the project directory variable, with the current directory as fallback."""
    return f'bash "${{CLAUDE_PROJECT_DIR:-.}}/{script}"'


COMMAND_TOOLS = "Bash|PowerShell"
FILE_TOOL_MATCHER = "Read|Edit|Write|NotebookEdit|Grep|Glob"


def test_settings_wire_the_three_hooks_for_both_shell_tools_and_the_file_tools() -> None:
    wiring = _wiring()
    assert set(wiring) == {COMMAND_TOOLS, FILE_TOOL_MATCHER}
    assert wiring[COMMAND_TOOLS] == [hook_command(script) for script in BASH_HOOKS]
    assert wiring[FILE_TOOL_MATCHER] == [hook_command(SECRETS)]


def test_every_hook_command_names_an_existing_script() -> None:
    for commands in _wiring().values():
        for command in commands:
            match = re.fullmatch(r'bash "\$\{CLAUDE_PROJECT_DIR:-\.\}/(hooks/[a-z-]+\.sh)"', command)
            assert match, command
            assert repo_path(match.group(1)).is_file()


def test_the_settings_commands_work_from_another_working_directory(tmp_path: Path) -> None:
    # Run the exact command strings of the settings in a different directory, with the project variable set the way
    # Claude Code sets it (an absolute path, native to the platform). A relative "hooks/..." would fail here.
    assert BASH is not None
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo_path())}
    command = _wiring()[COMMAND_TOOLS][0]
    allowed = subprocess.run(
        [BASH, "-c", command], input=json.dumps(bash_payload("git status")), cwd=tmp_path, env=env,
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert allowed.returncode == 0, allowed.stderr
    blocked = subprocess.run(
        [BASH, "-c", command], input=json.dumps(bash_payload("git commit -m message")), cwd=tmp_path, env=env,
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert blocked.returncode == 2 and blocked.stderr.strip()


# --- Bash commands that must be blocked: (command, the hook that must block it) ---

BLOCKED_BASH = [
    pytest.param("git commit -m message", DESTRUCTIVE, id="git-commit"),
    pytest.param("git push origin main", DESTRUCTIVE, id="git-push"),
    pytest.param("git push --force origin main", DESTRUCTIVE, id="git-push-force"),
    pytest.param("git push origin main --force-with-lease", DESTRUCTIVE, id="git-push-force-with-lease"),
    pytest.param("git reset --hard HEAD~1", DESTRUCTIVE, id="git-reset-hard"),
    pytest.param("git merge feature", DESTRUCTIVE, id="git-merge"),
    pytest.param("rm -rf /", DESTRUCTIVE, id="rm-rf-root"),
    pytest.param("rm -rf ~", DESTRUCTIVE, id="rm-rf-home"),
    pytest.param("rm -rf .", DESTRUCTIVE, id="rm-rf-dot"),
    pytest.param("terraform apply", NETWORK, id="terraform-apply"),
    pytest.param("terraform apply -auto-approve", NETWORK, id="terraform-apply-auto"),
    # Public invocation is a deliberate manual maintainer step, so the agent may never run it.
    pytest.param("gcloud run deploy oah-backend --allow-unauthenticated", NETWORK, id="gcloud-allow-unauthenticated"),
    pytest.param("gcloud run services update svc --allow-unauthenticated", NETWORK, id="gcloud-update-unauthenticated"),
    pytest.param("uvicorn oah.api.app:app --host 0.0.0.0", NETWORK, id="uvicorn-all-interfaces"),
    pytest.param("ngrok http 8000", NETWORK, id="ngrok"),
    pytest.param("cat .env", SECRETS, id="cat-env"),
    pytest.param("cat .env.local", SECRETS, id="cat-env-local"),
    pytest.param("type credentials.json", SECRETS, id="type-credentials"),
    pytest.param("Get-Content deploy/server.pem", SECRETS, id="get-content-pem"),
    pytest.param("cat ~/.ssh/id_rsa", SECRETS, id="cat-id-rsa"),
    pytest.param("cat ~/.ssh/id_ed25519", SECRETS, id="cat-id-ed25519"),
    pytest.param("cp store.pfx elsewhere", SECRETS, id="pfx"),
    pytest.param("cp store.p12 elsewhere", SECRETS, id="p12"),
    # --- Closed gaps: public invocation through IAM and the other ingress spellings ---
    pytest.param(
        "gcloud run services add-iam-policy-binding svc --member=allUsers --role=roles/run.invoker",
        NETWORK,
        id="iam-binding-all-users",
    ),
    pytest.param(
        "gcloud beta run services add-iam-policy-binding svc --member allUsers --role roles/run.invoker",
        NETWORK,
        id="iam-binding-beta",
    ),
    pytest.param(
        "gcloud alpha run services add-iam-policy-binding svc --role=roles/run.invoker --member='allUsers'",
        NETWORK,
        id="iam-binding-alpha-member-quoted",
    ),
    pytest.param(
        "gcloud run services add-iam-policy-binding svc --member=allAuthenticatedUsers --role=roles/run.invoker",
        NETWORK,
        id="iam-binding-all-authenticated-users",
    ),
    pytest.param("gcloud run services add-iam-policy-binding svc --member=ALLUSERS", NETWORK, id="iam-binding-case"),
    pytest.param("gcloud run services set-iam-policy svc policy.json", NETWORK, id="set-iam-policy"),
    pytest.param("gcloud run services update svc --no-invoker-iam-check", NETWORK, id="no-invoker-iam-check"),
    pytest.param("gcloud run deploy svc --ingress=all", NETWORK, id="ingress-equals-all"),
    pytest.param("gcloud run services update svc --ingress all", NETWORK, id="ingress-space-all-on-update"),
    pytest.param("gcloud.cmd run deploy svc --allow-unauthenticated", NETWORK, id="gcloud-cmd-wrapper"),
    pytest.param("terraform -chdir=infra apply", NETWORK, id="terraform-chdir-apply"),
    pytest.param("terraform destroy", NETWORK, id="terraform-destroy"),
    # --- Closed gaps: rm spellings ---
    pytest.param("rm -fr /", DESTRUCTIVE, id="rm-fr-flag-order"),
    pytest.param("rm -r -f /", DESTRUCTIVE, id="rm-separate-flags"),
    pytest.param("rm -f -r /", DESTRUCTIVE, id="rm-separate-flags-reversed"),
    pytest.param("rm --recursive --force /", DESTRUCTIVE, id="rm-long-flags"),
    pytest.param("rm --force --recursive build", DESTRUCTIVE, id="rm-long-flags-reversed"),
    pytest.param("rm -Rf build", DESTRUCTIVE, id="rm-capital-r"),
    pytest.param("rm -fR build", DESTRUCTIVE, id="rm-capital-r-after-f"),
    pytest.param("rm -r -f -v build", DESTRUCTIVE, id="rm-three-flags"),
    pytest.param("rm -r /", DESTRUCTIVE, id="rm-recursive-on-root-without-force"),
    pytest.param("rm -R ~", DESTRUCTIVE, id="rm-recursive-on-home-without-force"),
    pytest.param("rm -r *", DESTRUCTIVE, id="rm-recursive-on-star"),
    pytest.param("rm -rf --no-preserve-root /", DESTRUCTIVE, id="rm-no-preserve-root"),
    pytest.param("ls; rm -fr build", DESTRUCTIVE, id="rm-after-a-separator"),
    pytest.param("sudo /bin/rm -fr build", DESTRUCTIVE, id="rm-absolute-path"),
    pytest.param("bash -c 'rm -r -f build'", DESTRUCTIVE, id="rm-inside-bash-c"),
    pytest.param("Remove-Item -Recurse -Force build", DESTRUCTIVE, id="remove-item-recurse-force"),
    pytest.param("Remove-Item build -Force -Recurse", DESTRUCTIVE, id="remove-item-reversed"),
    pytest.param("rm -r -Force build", DESTRUCTIVE, id="powershell-rm-alias"),
    pytest.param("rd /s /q build", DESTRUCTIVE, id="cmd-rd"),
    # --- Closed gaps: SQL and git spellings ---
    pytest.param("psql -c 'DROP DATABASE prod'", DESTRUCTIVE, id="drop-database-upper-case"),
    pytest.param("psql -c 'Drop   Database prod'", DESTRUCTIVE, id="drop-database-mixed-case"),
    pytest.param("psql -c 'TRUNCATE TABLE samples'", DESTRUCTIVE, id="truncate-table-upper-case"),
    pytest.param("git push -f origin main", DESTRUCTIVE, id="git-push-short-force"),
    pytest.param("git push origin +main", DESTRUCTIVE, id="git-push-plus-ref"),
    pytest.param("git push origin +HEAD:main", DESTRUCTIVE, id="git-push-plus-refspec"),
    pytest.param("git -C elsewhere commit -m message", DESTRUCTIVE, id="git-dash-C-commit"),
    pytest.param("git -c user.name=x commit -m message", DESTRUCTIVE, id="git-dash-c-commit"),
    pytest.param("git --git-dir=elsewhere/.git push origin main", DESTRUCTIVE, id="git-dir-push"),
    pytest.param("git --no-pager -C elsewhere merge feature", DESTRUCTIVE, id="git-pager-merge"),
    pytest.param("git status && git commit -m message", DESTRUCTIVE, id="git-commit-after-and"),
    pytest.param("GIT COMMIT -m message", DESTRUCTIVE, id="git-commit-upper-case"),
    pytest.param("git clean -fd", DESTRUCTIVE, id="git-clean-fd"),
    pytest.param("git clean -fdx", DESTRUCTIVE, id="git-clean-fdx"),
    pytest.param("git clean -d -f", DESTRUCTIVE, id="git-clean-separate-flags"),
    pytest.param("git clean --force", DESTRUCTIVE, id="git-clean-long-force"),
    pytest.param("git checkout -- .", DESTRUCTIVE, id="git-checkout-dash-dash-dot"),
    pytest.param("git checkout .", DESTRUCTIVE, id="git-checkout-dot"),
    pytest.param("git checkout --force main", DESTRUCTIVE, id="git-checkout-force"),
    pytest.param("git restore .", DESTRUCTIVE, id="git-restore-dot"),
    pytest.param("git restore -- .", DESTRUCTIVE, id="git-restore-dash-dash-dot"),
    pytest.param("git restore --source=HEAD~1 :/", DESTRUCTIVE, id="git-restore-top-level"),
    pytest.param("git restore --staged --worktree .", DESTRUCTIVE, id="git-restore-staged-and-worktree"),
    pytest.param("git -C elsewhere reset --hard", DESTRUCTIVE, id="git-dash-C-reset-hard"),
    # --- Closed gaps: more secret-file names and globs that expand to them ---
    pytest.param("cat .npmrc", SECRETS, id="npmrc"),
    pytest.param("type .netrc", SECRETS, id="netrc"),
    pytest.param("Get-Content deploy/signing.key", SECRETS, id="key-file"),
    pytest.param("cat AuthKey_ABC123.p8", SECRETS, id="p8"),
    pytest.param("cp release.jks elsewhere", SECRETS, id="jks"),
    pytest.param("cat infra/prod.tfvars", SECRETS, id="tfvars"),
    pytest.param("cat infra/prod.auto.tfvars.json", SECRETS, id="tfvars-json"),
    pytest.param("cat terraform.tfstate", SECRETS, id="tfstate"),
    pytest.param("cat terraform.tfstate.backup", SECRETS, id="tfstate-backup"),
    pytest.param("cat deploy/service-account.json", SECRETS, id="service-account-json"),
    pytest.param("cat keys/my_service_account_prod.json", SECRETS, id="service-account-underscore"),
    pytest.param("cat gcp-credentials-prod.yaml", SECRETS, id="credentials-in-the-name"),
    pytest.param("cat ~/.aws/credentials", SECRETS, id="credentials-file"),
    pytest.param("cat .e*", SECRETS, id="glob-dotenv"),
    pytest.param("cat .en[v]", SECRETS, id="glob-bracket-dotenv"),
    pytest.param("cat deploy/*.pem", SECRETS, id="glob-pem"),
    pytest.param("cat *.p?2", SECRETS, id="glob-question-mark"),
    pytest.param("Get-Content keys/id_*", SECRETS, id="glob-id-prefix"),
    pytest.param("cat cred*", SECRETS, id="glob-credentials-prefix"),
    pytest.param("cat service*account*", SECRETS, id="glob-service-account-prefix"),
    pytest.param("cat --glob=*.tfstate*", SECRETS, id="glob-in-an-option"),
]


@pytest.mark.parametrize(("command", "hook"), BLOCKED_BASH)
def test_bash_command_is_blocked_by_the_expected_hook(command: str, hook: str) -> None:
    result = run_hook(hook, bash_payload(command))
    assert result.returncode == 2, f"{hook} let {command!r} through"
    assert result.stderr.strip(), "a blocking hook must tell the agent why"
    assert result.stdout == ""


# --- Secret and key files through the file tools ---

BLOCKED_PATHS = [
    ".env",
    ".env.example",
    ".env.production",
    "deploy/.env",
    "certs/server.pem",
    "credentials.json",
    "config/credentials.json",
    "keys/id_rsa",
    "keys/id_ed25519",
    "keys/store.pfx",
    "keys/store.p12",
    ".npmrc",
    "web/.npmrc",
    "home/.netrc",
    "keys/signing.key",
    "keys/AuthKey_ABC123.p8",
    "keys/release.jks",
    "infra/prod.tfvars",
    "infra/terraform.tfstate",
    "infra/terraform.tfstate.backup",
    "deploy/service-account.json",
    "deploy/service_account_prod.yaml",
    "home\\.aws\\credentials",
    "deploy\\gcp-credentials.json",
]


# Each path is tried with one of the three file_path tools in turn.
FILE_TOOLS = ("Read", "Edit", "Write")


@pytest.mark.parametrize(("tool", "path"), [(FILE_TOOLS[i % 3], path) for i, path in enumerate(BLOCKED_PATHS)])
def test_secret_files_are_blocked_through_the_file_tools(tool: str, path: str) -> None:
    result = run_hook(SECRETS, file_payload(tool, path))
    assert result.returncode == 2
    assert path in result.stderr


def tool_payload(tool: str, **tool_input: object) -> dict[str, object]:
    return {"tool_name": tool, "tool_input": tool_input}


BLOCKED_OTHER_TOOLS = [
    pytest.param(tool_payload("NotebookEdit", notebook_path="notes/.env"), id="notebook-edit-env"),
    pytest.param(tool_payload("NotebookEdit", notebook_path="keys/server.pem", new_source="x"), id="notebook-edit-pem"),
    pytest.param(tool_payload("Grep", pattern="KEY", path=".env"), id="grep-path-env"),
    pytest.param(tool_payload("Grep", pattern="KEY", path="deploy/service-account.json"), id="grep-path-service-account"),
    pytest.param(tool_payload("Grep", pattern="KEY", glob="*.pem"), id="grep-glob-pem"),
    pytest.param(tool_payload("Grep", pattern="KEY", glob=".env*"), id="grep-glob-env"),
    pytest.param(tool_payload("Grep", pattern="x", path="infra/terraform.tfstate"), id="grep-tfstate"),
    pytest.param(tool_payload("Glob", pattern="**/.env"), id="glob-env"),
    pytest.param(tool_payload("Glob", pattern="**/*.pem"), id="glob-pem"),
    pytest.param(tool_payload("Glob", pattern="**/credentials*"), id="glob-credentials"),
    pytest.param(tool_payload("Glob", pattern="*.tf*"), id="glob-terraform"),
]


@pytest.mark.parametrize("payload", BLOCKED_OTHER_TOOLS)
def test_secret_files_are_blocked_through_notebook_grep_and_glob(payload: dict[str, object]) -> None:
    result = run_hook(SECRETS, payload)
    assert result.returncode == 2
    assert result.stderr.strip()


ALLOWED_OTHER_TOOLS = [
    pytest.param(tool_payload("NotebookEdit", notebook_path="notebooks/analysis.ipynb"), id="notebook-edit"),
    pytest.param(tool_payload("Grep", pattern="\\.env|KEY", path="src", glob="*.py"), id="grep-pattern-is-not-a-path"),
    pytest.param(tool_payload("Grep", pattern="x"), id="grep-no-path"),
    pytest.param(tool_payload("Glob", pattern="**/*.py"), id="glob-python"),
    pytest.param(tool_payload("Glob", pattern="docs/*.md", path="docs"), id="glob-markdown"),
    pytest.param(tool_payload("Glob", pattern="**/*"), id="glob-everything"),
    pytest.param(tool_payload("Glob", pattern="tests/unit/test_*.py"), id="glob-tests"),
]


@pytest.mark.parametrize("payload", ALLOWED_OTHER_TOOLS)
def test_ordinary_notebook_grep_and_glob_calls_are_allowed(payload: dict[str, object]) -> None:
    result = run_hook(SECRETS, payload)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("script", BASH_HOOKS)
def test_the_powershell_tool_payload_is_judged_like_a_bash_payload(script: str) -> None:
    # The PowerShell tool carries its command text in the same tool_input.command field (assumption taken from the
    # Claude Code tool schema; not observed in a live session from here).
    cases = {
        DESTRUCTIVE: "Remove-Item -Recurse -Force build",
        NETWORK: "gcloud run services add-iam-policy-binding svc --member=allUsers",
        SECRETS: "Get-Content .env.production",
    }
    blocked = run_hook(script, {"tool_name": "PowerShell", "tool_input": {"command": cases[script]}})
    assert blocked.returncode == 2 and blocked.stderr.strip()
    allowed = run_hook(script, {"tool_name": "PowerShell", "tool_input": {"command": "Get-ChildItem docs"}})
    assert allowed.returncode == 0


# --- Allowed: ordinary work must not be blocked by any of the three hooks ---

ALLOWED_BASH = [
    "python -m pytest -q tests/unit",
    "pytest -q",
    "python -m ruff check src scripts tests",
    "python -m mypy",
    "git status",
    "git status --short",
    "git diff",
    "git diff --stat",
    "git log --oneline -5",
    "git branch --show-current",
    "terraform plan",
    "terraform validate",
    "gcloud run services describe oah-backend --region us-central1",
    "gcloud run revisions list --service oah-backend",
    "ls docs",
    "rm temporary-file.txt",
    "rm -f temporary-file.txt",
    "rm -v one.txt two.txt",
    "rm -r --interactive scratch",
    "git add -A",
    "git add .",
    "git diff .",
    "git status .",
    "git checkout -b feature/new-work",
    "git checkout main",
    "git checkout -- src/oah/config.py",
    "git restore src/oah/config.py",
    "git restore --staged .",
    "git clean -n",
    "git -C elsewhere status",
    "git -c core.pager=cat log --oneline -3",
    "git stash list",
    "gcloud run services get-iam-policy oah-backend --region us-central1",
    "gcloud run services remove-iam-policy-binding svc --member=allUsers --role=roles/run.invoker",
    "gcloud run deploy svc --ingress=internal-and-cloud-load-balancing",
    "gcloud run services update svc --ingress internal",
    "terraform -chdir=infra plan",
    "psql -c 'select 1'",
    "python -c \"print('drop')\"",
    "ls *",
    "ls docs/*.md",
    "ls *.*",
    "grep -rn 'foo.*bar' src",
    "ruff check --select I src",
    "Get-ChildItem docs",
    "Select-String -Path docs/*.md -Pattern deploy",
    "cat src/oah/config.py",
]


@pytest.mark.parametrize("command", ALLOWED_BASH)
def test_ordinary_bash_commands_are_allowed(command: str) -> None:
    for script in BASH_HOOKS:
        result = run_hook(script, bash_payload(command))
        assert result.returncode == 0, f"{script} blocked {command!r}: {result.stderr}"


ALLOWED_PATHS = ["src/oah/config.py", "docs/deployment.md", "docs/environment_setup.md", "README.md", "tests/unit/test_api.py"]


@pytest.mark.parametrize(("tool", "path"), [(FILE_TOOLS[i % 3], path) for i, path in enumerate(ALLOWED_PATHS)])
def test_normal_files_are_allowed_through_the_file_tools(tool: str, path: str) -> None:
    assert run_hook(SECRETS, file_payload(tool, path)).returncode == 0


def test_a_payload_without_a_command_or_path_is_allowed() -> None:
    for script in BASH_HOOKS:
        assert run_hook(script, {"tool_name": "Grep", "tool_input": {"pattern": "x"}}).returncode == 0


# --- Fail closed: a hook that cannot decide blocks (exit 2), it never fails open (exit 127 or 5) ---

MALFORMED_INPUTS = [
    pytest.param("not json", id="plain-text"),
    pytest.param("", id="empty"),
    pytest.param("   \n", id="whitespace"),
    pytest.param('{"tool_name": "Bash", "tool_input": {"command": ', id="truncated-json"),
    pytest.param("[1, 2, 3]", id="json-array"),
    pytest.param('"a string"', id="json-string"),
    pytest.param('{"tool_name": "Bash", "tool_input": "git status"}', id="tool-input-is-a-string"),
    pytest.param('{"tool_name": "Bash", "tool_input": ["git", "status"]}', id="tool-input-is-an-array"),
]


@pytest.mark.parametrize("script", BASH_HOOKS)
@pytest.mark.parametrize("text", MALFORMED_INPUTS)
def test_hooks_fail_closed_on_malformed_input(script: str, text: str) -> None:
    result = run_hook_text(script, text)
    assert result.returncode == 2, f"{script} exit {result.returncode} for {text!r}"
    assert "fail closed" in result.stderr


@pytest.mark.parametrize("script", BASH_HOOKS)
def test_hooks_fail_closed_when_jq_is_missing(script: str, tmp_path: Path) -> None:
    # An empty directory as the whole PATH: no jq (and no other external program). The hooks use builtins up to the
    # jq check, so the message is still printed. Exit 127 here would mean "command not found" and would not block.
    env = {**os.environ, "PATH": str(tmp_path)}
    result = run_hook_text(script, json.dumps(bash_payload("git status")), env=env)
    assert result.returncode == 2
    assert "jq" in result.stderr and "install" in result.stderr.lower()


@pytest.mark.parametrize("script", BASH_HOOKS)
def test_hooks_fail_closed_when_the_shared_library_is_missing(script: str, tmp_path: Path) -> None:
    target = tmp_path / "hooks"
    target.mkdir()
    (target / Path(script).name).write_text(repo_path(script).read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    result = run_hook_text(str(target / Path(script).name), json.dumps(bash_payload("git status")))
    assert result.returncode == 2 and "fail closed" in result.stderr


@pytest.mark.parametrize("script", BASH_HOOKS)
def test_a_payload_without_tool_input_is_allowed(script: str) -> None:
    assert run_hook(script, {"tool_name": "Bash"}).returncode == 0


# --- Gaps consciously left ---


@pytest.mark.xfail(strict=True, reason="known false positive: the dotted-name pattern also matches the Python module attribute")
def test_python_environment_access_is_not_mistaken_for_a_secret_file() -> None:
    assert run_hook(SECRETS, bash_payload("python -c 'import os; os.environ'")).returncode == 0


# --- Discovery of a working bash (these run even where no bash exists) ---


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _healthy_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
    return _completed(0, PROBE_MARKER + "\n")


def _broken_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
    return _completed(1, "", "WSL (9 - Relay) ERROR: execvpe(/bin/bash) failed")


def _touch(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return str(path)


def test_discovery_reports_a_missing_bash(tmp_path: Path) -> None:
    path, reason = find_working_bash(
        which=lambda name: None, run=_healthy_run, environ={}, platform="linux"
    )
    assert path is None and "no working bash was found" in reason


def test_discovery_rejects_the_wsl_launcher_in_the_system_folder(tmp_path: Path) -> None:
    stub = _touch(tmp_path / "Windows" / "System32" / "bash.exe")
    environ = {"SystemRoot": str(tmp_path / "Windows")}
    # Even a stub whose probe would succeed is never accepted: the folder alone disqualifies it.
    path, reason = find_working_bash(
        which=lambda name: stub if name == "bash" else None, run=_healthy_run, environ=environ, platform="win32"
    )
    assert path is None
    assert "the WSL launcher does not count" in reason


def test_discovery_rejects_a_bash_that_fails_the_probe(tmp_path: Path) -> None:
    broken = _touch(tmp_path / "somewhere" / "bash.exe")
    path, reason = find_working_bash(
        which=lambda name: broken if name == "bash" else None, run=_broken_run, environ={}, platform="win32"
    )
    assert path is None and "failed the probe" in reason


def test_discovery_prefers_git_for_windows_over_the_path(tmp_path: Path) -> None:
    git = _touch(tmp_path / "Git" / "cmd" / "git.exe")
    git_bash = _touch(tmp_path / "Git" / "bin" / "bash.exe")
    other = _touch(tmp_path / "other" / "bash.exe")
    tools = {"git": git, "bash": other, "jq": "jq"}
    path, reason = find_working_bash(which=tools.get, run=_healthy_run, environ={}, platform="win32")
    assert (path, reason) == (git_bash, "")


def test_discovery_skips_a_broken_candidate_and_takes_the_next(tmp_path: Path) -> None:
    git = _touch(tmp_path / "Git" / "cmd" / "git.exe")
    broken = _touch(tmp_path / "Git" / "bin" / "bash.exe")
    working = _touch(tmp_path / "other" / "bash.exe")

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return _healthy_run() if command[0] == working else _broken_run()

    tools = {"git": git, "bash": working, "jq": "jq"}
    path, _ = find_working_bash(which=tools.get, run=run, environ={}, platform="win32")
    assert path == working and broken != working


def test_discovery_reports_a_missing_jq(tmp_path: Path) -> None:
    good = _touch(tmp_path / "bin" / "bash")
    path, reason = find_working_bash(
        which=lambda name: good if name == "bash" else None, run=_healthy_run, environ={}, platform="linux"
    )
    assert path is None and "jq was not found" in reason


def test_discovery_probe_survives_a_start_failure(tmp_path: Path) -> None:
    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise OSError("cannot start")

    path, reason = find_working_bash(which=lambda name: "bash" if name == "bash" else None, run=run, environ={}, platform="linux")
    assert path is None and "failed the probe" in reason


def test_discovery_run_hook_reports_an_unusable_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.modules[__name__], "BASH", "unusable-bash")
    monkeypatch.setattr(subprocess, "run", _broken_run)
    with pytest.raises(pytest.fail.Exception, match="interpreter is not usable"):
        run_hook(SECRETS, bash_payload("ls"))
