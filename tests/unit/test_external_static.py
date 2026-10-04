"""Static guards for the external-context package: one network path, no user-supplied target, no stray host."""
from __future__ import annotations

import re

from oah.external.constants import ALLOWED_HOSTS
from oah.paths import source_path

PACKAGE = source_path("external")
SOURCES = sorted(PACKAGE.glob("*.py"))
# Hosts that may appear in text (attribution and documentation links, never fetched).
DISPLAY_HOSTS = {"open-meteo.com", "doi.org", "www.gbif.org"}
URL = re.compile(r"https?://([A-Za-z0-9.-]+)")


def test_the_package_has_the_expected_modules() -> None:
    assert {path.stem for path in SOURCES} >= {
        "constants", "coords", "envelope", "gbif", "guard", "http", "openmeteo", "runtime", "service", "settings", "sites", "taxa",
    }


def test_only_the_http_module_touches_an_http_library() -> None:
    offenders = []
    for path in SOURCES:
        text = path.read_text(encoding="utf-8")
        if path.name != "http.py" and re.search(r"^\s*(?:import|from)\s+(?:httpx|requests|urllib\.request|http\.client|socket|aiohttp)\b", text, re.MULTILINE):
            offenders.append(path.name)
    assert offenders == []


def test_no_module_other_than_constants_writes_a_url_or_host() -> None:
    offenders = []
    for path in SOURCES:
        if path.name in {"constants.py", "settings.py"}:
            continue
        for host in URL.findall(path.read_text(encoding="utf-8")):
            if host not in ALLOWED_HOSTS and host not in DISPLAY_HOSTS:
                offenders.append((path.name, host))
    assert offenders == []


def test_every_url_host_in_the_package_is_known() -> None:
    hosts = set()
    for path in SOURCES:
        hosts.update(URL.findall(path.read_text(encoding="utf-8")))
    assert hosts <= ALLOWED_HOSTS | DISPLAY_HOSTS | {"example.org"}


def test_the_allow_list_is_exactly_the_three_documented_hosts() -> None:
    assert ALLOWED_HOSTS == {"archive-api.open-meteo.com", "flood-api.open-meteo.com", "api.gbif.org"}


def test_the_http_client_never_enables_automatic_redirects_or_disables_certificate_checks() -> None:
    text = (PACKAGE / "http.py").read_text(encoding="utf-8")
    assert "follow_redirects=False" in text and "verify=True" in text
    assert "verify=False" not in text and "follow_redirects=True" not in text


def test_no_module_logs_or_prints_a_url_or_coordinates() -> None:
    for path in SOURCES:
        text = path.read_text(encoding="utf-8")
        assert "print(" not in text
        for call in re.findall(r"LOGGER\.\w+\(([^)]*)\)", text):
            assert "latitude" not in call and "longitude" not in call and "url" not in call.lower().replace("%s", "")
