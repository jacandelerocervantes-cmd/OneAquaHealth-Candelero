"""Test isolation shared by every test.

- The developer's local dotenv file must never influence a test: `_dotenv_values` is stubbed to an
  empty mapping.
- Data written by the code under test (review database, audit trails, exports) goes to a temporary
  directory, never to the real external data directory.
- The API now fails closed without OAH_API_KEY; tests that exercise the open local-demo mode get the
  explicit opt-in flag by default, and tests of the closed behaviour remove it.
"""
import pytest
from hypothesis import settings

from oah import config

# Property tests run numerical loops whose duration depends on the machine; a per-example deadline
# only produces intermittent failures (seen on 2026-09-26), never information. Correctness is checked
# by the assertions, not by wall-clock time.
settings.register_profile("oah", deadline=None)
settings.load_profile("oah")


@pytest.fixture(autouse=True)
def _fresh_scope_guard():
    """The country-scope result cache is process-wide; a test must never be answered from another test's result."""
    from oah.indices.scope_guard import GUARD

    GUARD.clear()
    yield
    GUARD.clear()


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "_dotenv_values", lambda: {})
    monkeypatch.setenv("OAH_DATA_DIR", str(tmp_path / "oah-data"))
    monkeypatch.setenv("OAH_INSECURE_NO_AUTH", "1")
