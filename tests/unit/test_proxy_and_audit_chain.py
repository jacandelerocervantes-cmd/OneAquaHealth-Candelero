"""Audit item 4: trusted-proxy client addresses, HSTS, hash-chained rotating LLM audit log, model default."""

import json

import pytest

from oah import config
from oah.api.client_ip import client_key, is_https
from oah.explain import audit

TRUSTED = frozenset({"10.0.0.1", "10.0.0.2"})


# --- client key ---------------------------------------------------------------------------------------------
def test_forwarded_for_is_ignored_unless_the_peer_is_a_trusted_proxy():
    assert client_key("203.0.113.9", "1.2.3.4", TRUSTED) == "203.0.113.9"  # any client can send that header
    assert client_key("10.0.0.1", "1.2.3.4", TRUSTED) == "1.2.3.4"
    assert client_key("10.0.0.1", None, TRUSTED) == "10.0.0.1"
    assert client_key(None, "1.2.3.4", TRUSTED) == "unknown"


def test_the_chain_is_read_from_the_right_and_spoofed_left_entries_are_ignored():
    assert client_key("10.0.0.1", "6.6.6.6, 1.2.3.4", TRUSTED) == "1.2.3.4"  # 6.6.6.6 was client-supplied
    assert client_key("10.0.0.1", "1.2.3.4, 10.0.0.2", TRUSTED) == "1.2.3.4"  # a second trusted hop is skipped
    assert client_key("10.0.0.1", "10.0.0.2", TRUSTED) == "10.0.0.1"  # nothing but proxies: fall back to the peer


@pytest.mark.parametrize("header", ["not-an-ip", "1.2.3.4, bogus", "1.2.3.4,,", "<script>"])
def test_a_malformed_chain_falls_back_to_the_peer_never_a_guess(header):
    result = client_key("10.0.0.1", header, TRUSTED)
    assert result in {"10.0.0.1", "1.2.3.4"}
    if "bogus" in header or "not-an-ip" in header or "script" in header:
        assert result == "10.0.0.1"


def test_https_is_recognised_directly_or_through_a_trusted_proxy_only():
    assert is_https("https", "203.0.113.9", None, TRUSTED)
    assert is_https("http", "10.0.0.1", "https", TRUSTED)
    assert not is_https("http", "203.0.113.9", "https", TRUSTED)  # untrusted peer cannot claim https
    assert not is_https("http", "10.0.0.1", "http", TRUSTED)


def test_trusted_proxies_setting_accepts_addresses_and_rejects_anything_else():
    assert config.load_settings({}).trusted_proxies == ()
    assert config.load_settings({"OAH_TRUSTED_PROXIES": "10.0.0.1, ::1"}).trusted_proxies == ("10.0.0.1", "::1")
    for bad in ("10.0.0.0/8", "proxy.example.test", "10.0.0.1,*"):
        with pytest.raises(ValueError):
            config.load_settings({"OAH_TRUSTED_PROXIES": bad})


def test_the_hsts_header_is_sent_only_over_https():
    from fastapi.testclient import TestClient

    from oah.api.app import app

    client = TestClient(app)
    assert "Strict-Transport-Security" not in client.get("/health").headers
    secure = TestClient(app, base_url="https://testserver").get("/health")
    assert secure.headers["Strict-Transport-Security"] == "max-age=31536000"


# --- model default ------------------------------------------------------------------------------------------
def test_the_default_model_is_sonnet_and_can_be_overridden():
    assert config.load_settings({}).llm_model == "claude-sonnet-5-5"
    assert config.load_settings({"OAH_LLM_MODEL": "claude-opus-5-5"}).llm_model == "claude-opus-5-5"


# --- LLM audit chain ----------------------------------------------------------------------------------------
@pytest.fixture()
def log(tmp_path, monkeypatch):
    path = tmp_path / "audit" / "llm_calls.jsonl"
    monkeypatch.setattr(audit, "llm_audit_path", lambda name="llm_calls.jsonl": path)
    return path


def test_records_are_chained_and_verify(log):
    for index in range(3):
        audit.record("dispatch", n=index)
    assert audit.verify_chain(log) == (True, 3, None)
    lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["prev_hash"] == "" and lines[1]["prev_hash"] == lines[0]["hash"]


def test_an_edited_removed_or_reordered_record_breaks_the_chain(log):
    for index in range(4):
        audit.record("dispatch", n=index)
    lines = log.read_text(encoding="utf-8").splitlines()

    log.write_text("\n".join(lines[:1] + [lines[1].replace('"n": 1', '"n": 9')] + lines[2:]) + "\n", encoding="utf-8")
    assert audit.verify_chain(log)[:1] == (False,)

    log.write_text("\n".join(lines[:1] + lines[2:]) + "\n", encoding="utf-8")  # a middle record removed
    assert audit.verify_chain(log) == (False, 1, 2)

    log.write_text("\n".join([lines[0], lines[2], lines[1], lines[3]]) + "\n", encoding="utf-8")  # reordered
    assert audit.verify_chain(log)[0] is False


def test_the_log_rotates_and_the_chain_continues_across_files(log, monkeypatch):
    monkeypatch.setattr(audit, "MAX_LOG_BYTES", 300)
    monkeypatch.setattr(audit, "MAX_ROTATED_FILES", 1000)  # pruning has its own tests (tests/unit/test_audit_log_hardening.py)
    for index in range(12):
        audit.record("dispatch", n=index, filler="x" * 40)
    rotated = sorted(log.parent.glob("llm_calls.*.jsonl"))
    assert rotated, "the log should have rotated"
    assert audit.verify_all() == (True, 12, None)
    # tampering with a rotated file is caught by the whole-chain check
    first = rotated[0]
    first.write_text(first.read_text(encoding="utf-8").replace('"n": 0', '"n": 7'), encoding="utf-8")
    ok, _, where = audit.verify_all()
    assert ok is False and where is not None


def test_lines_written_before_the_chain_existed_are_skipped(log):
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps({"timestamp": "2026-01-01T00:00:00+00:00", "event": "old"}) + "\n", encoding="utf-8")
    audit.record("dispatch")
    assert audit.verify_chain(log) == (True, 1, None)


def test_an_unwritable_log_still_raises_oserror(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    monkeypatch.setattr(audit, "llm_audit_path", lambda name="llm_calls.jsonl": blocker / "audit" / name)
    with pytest.raises(OSError):
        audit.record("dispatch")
