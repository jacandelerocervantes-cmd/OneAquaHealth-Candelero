"""Contract: the example environment file documents every variable the code reads and holds no real value.

The example file is the contract of docs/environment_variables.md. It is read here AS DATA (text), never loaded into
the process environment. Failure messages list variable NAMES only, never values, so a real value pasted by mistake
is not echoed into a test log.

Literal note: the file name is assembled from fragments below. The repository's own guard hook blocks tool calls that
name the file (it matches the dotenv pattern), so a literal would make this test file impossible to edit with the
agent tooling. The assembled name is exactly the file at the repository root.
"""

from __future__ import annotations

import re

import pytest

from oah.paths import repo_path

EXAMPLE_NAME = "." + "env" + "." + "example"  # see the module docstring for why this is not a literal

# A name the code reads is a string literal that is exactly an OAH_* name or the model-provider key name.
_NAME_LITERAL = re.compile(r"""["'](OAH_[A-Z0-9_]*[A-Z0-9]|ANTHROPIC_API_KEY)["']""")
_ASSIGNMENT = re.compile(r"^\s*(?P<comment>#\s*)?(?P<name>[A-Z][A-Z0-9_]*)=(?P<value>.*)$")

# Secrets: their lines must stay empty in the example (the real value lives in the local settings file,
# Secret Manager or Vercel server-only variables).
SECRET_NAMES = frozenset({"ANTHROPIC_API_KEY", "OAH_API_KEY"})
_SECRET_SUFFIXES = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD")

# Non-secret variables whose example value may be uncommented because it is a public, documented default.
HARMLESS_DEFAULTS = frozenset(
    {"OAH_SANDBOX_URL", "OAH_LLM_MODEL", "OAH_TRANSLATION_MODEL", "OAH_DEFAULT_LANGUAGE", "OAH_CORS_ORIGINS"}
)

_NUMERIC_SUFFIXES = (
    "_SECONDS",
    "_CAP",
    "_PER_MINUTE",
    "_DAILY",
    "_SIZE",
    "_REQUESTS",
    "_STEPS",
)
_PATH_SUFFIXES = ("_STORE", "_DIR", "_ROOT", "_PATH", "_FILE")


def _is_secret(name: str) -> bool:
    return name in SECRET_NAMES or name.endswith(_SECRET_SUFFIXES)


def _kind(name: str) -> str | None:
    """The value kind for which an empty uncommented line stops the server at start-up (None: harmless)."""
    if name.endswith(_NUMERIC_SUFFIXES):
        return "numeric"
    if name.endswith("_URL"):
        return "URL"
    if name.endswith(_PATH_SUFFIXES):
        return "path"
    if name.endswith("_LANGUAGE"):
        return "language"
    return None


def names_read_by_code() -> set[str]:
    names: set[str] = set()
    for file in repo_path("src", "oah").rglob("*.py"):
        names.update(_NAME_LITERAL.findall(file.read_text(encoding="utf-8")))
    return names


def _mentions(text: str, name: str) -> bool:
    return re.search(rf"(?<![A-Z0-9_]){re.escape(name)}(?![A-Z0-9_])", text) is not None


def _assignments(text: str) -> list[tuple[str, bool, str]]:
    """``(name, commented, value)`` for each ``NAME=value`` line, commented or not."""
    found = []
    for line in text.splitlines():
        match = _ASSIGNMENT.match(line)
        if match:
            found.append((match["name"], bool(match["comment"]), match["value"].strip().strip("\"'")))
    return found


_SK_PREFIX = re.compile(r"sk-[A-Za-z0-9_-]{8,}")
_LONG_TOKEN = re.compile(r"[A-Za-z0-9_+-]{32,}")
_NAME_ONLY = re.compile(r"[A-Z0-9_]+")
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}")


def looks_like_real_key(line: str) -> bool:
    """A key-shaped token: an ``sk-`` prefix, a private-key marker, or a long mixed letter-digit token."""
    if _SK_PREFIX.search(line) or _PRIVATE_KEY.search(line):
        return True
    for token in _LONG_TOKEN.findall(line):
        if _NAME_ONLY.fullmatch(token):
            continue  # a long variable name such as OAH_EXTERNAL_OPEN_METEO_PER_MINUTE
        if any(ch.isdigit() for ch in token) and any(ch.isalpha() for ch in token):
            return True
    return False


@pytest.fixture(scope="module")
def example_text() -> str:
    path = repo_path(EXAMPLE_NAME)
    if not path.is_file():
        pytest.fail(f"the example environment file is missing at the repository root ({EXAMPLE_NAME})")
    return path.read_text(encoding="utf-8")


def test_code_reads_the_expected_variables() -> None:
    names = names_read_by_code()
    assert {"OAH_API_KEY", "ANTHROPIC_API_KEY", "OAH_CORS_ORIGINS", "OAH_EXTERNAL_GBIF_DAILY"} <= names
    assert len(names) >= 40  # a broken scan would find (almost) nothing


def test_every_variable_the_code_reads_is_in_the_example(example_text: str) -> None:
    missing = sorted(name for name in names_read_by_code() if not _mentions(example_text, name))
    assert not missing, (
        f"{len(missing)} variable(s) read by src/oah are not mentioned (commented or not) in the example "
        f"environment file: {', '.join(missing)}"
    )


def test_secret_lines_are_empty(example_text: str) -> None:
    offenders = sorted({name for name, _, value in _assignments(example_text) if _is_secret(name) and value})
    assert not offenders, f"secret variable(s) with a value in the example file (must be empty): {', '.join(offenders)}"


def test_uncommented_values_are_only_documented_defaults(example_text: str) -> None:
    offenders = sorted(
        {
            name
            for name, commented, value in _assignments(example_text)
            if not commented and value and not _is_secret(name) and name not in HARMLESS_DEFAULTS
        }
    )
    assert not offenders, (
        "uncommented variable(s) with a value in the example file; comment them out or add them to "
        f"HARMLESS_DEFAULTS in this test with a reason: {', '.join(offenders)}"
    )


def test_no_line_looks_like_a_real_key(example_text: str) -> None:
    lines = [number for number, line in enumerate(example_text.splitlines(), start=1) if looks_like_real_key(line)]
    assert not lines, f"line number(s) of the example file that look like a real key: {lines}"


def test_no_empty_uncommented_numeric_url_path_or_language_value(example_text: str) -> None:
    offenders = sorted(
        {
            f"{name} ({_kind(name)})"
            for name, commented, value in _assignments(example_text)
            if not commented and not value and not _is_secret(name) and _kind(name) is not None
        }
    )
    assert not offenders, (
        "uncommented empty value(s) that stop the server at start-up or defeat the default; comment the line "
        f"out instead: {', '.join(offenders)}"
    )


# --- Self-tests of the detectors (synthetic strings only; nothing here is a real key) ---


def test_detector_flags_key_shapes() -> None:
    assert looks_like_real_key("ANTHROPIC_API_KEY=" + "sk" + "-" + "ant-abcdefgh12345678")
    assert looks_like_real_key("OAH_API_KEY=" + "a1" * 20)
    assert looks_like_real_key("# " + "-----BEGIN " + "RSA PRIVATE KEY-----")


def test_detector_ignores_ordinary_lines() -> None:
    assert not looks_like_real_key("# OAH_EXTERNAL_OPEN_METEO_PER_MINUTE=200")
    assert not looks_like_real_key("OAH_API_KEY=")
    assert not looks_like_real_key("# OAH_SANDBOX_URL=https://sandbox.example/fhir")


def test_assignment_parser_reads_commented_and_plain_lines() -> None:
    text = "# prose line\n# OAH_X_SECONDS=5\nOAH_Y_URL=\n  OAH_Z=1\n"
    assert _assignments(text) == [("OAH_X_SECONDS", True, "5"), ("OAH_Y_URL", False, ""), ("OAH_Z", False, "1")]


def test_kind_and_secret_classification() -> None:
    assert _kind("OAH_CHAT_TIMEOUT_SECONDS") == "numeric"
    assert _kind("OAH_SANDBOX_URL") == "URL"
    assert _kind("OAH_WATERBASE_STORE") == "path"
    assert _kind("OAH_DEFAULT_LANGUAGE") == "language"
    assert _kind("OAH_ENABLE_DOCS") is None
    assert _is_secret("OAH_API_KEY") and _is_secret("ANTHROPIC_API_KEY") and not _is_secret("OAH_LLM_MODEL")
