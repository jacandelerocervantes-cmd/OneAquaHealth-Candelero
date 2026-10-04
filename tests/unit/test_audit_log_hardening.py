"""The LLM audit log holds digests only, is mirrored to stdout as structured JSON, and keeps a bounded number of rotated
files (security audit F9)."""
import json

import pytest

from oah.explain import audit


@pytest.fixture()
def log(tmp_path, monkeypatch):
    path = tmp_path / "audit" / "llm_calls.jsonl"
    monkeypatch.setattr(audit, "llm_audit_path", lambda name="llm_calls.jsonl": path)
    return path


# --- no user text ---------------------------------------------------------------------------------------------------
def test_there_is_no_excerpt_helper_and_the_module_says_digest_only():
    assert not hasattr(audit, "redacted_excerpt") and not hasattr(audit, "_EXCERPT_REDACTIONS")
    doc = (audit.__doc__ or "").replace("\n", " ")
    assert "never holds user text" in doc and "DIGESTS" in doc


def test_a_chat_dispatch_record_has_the_digest_and_length_of_the_question_only():
    import inspect

    from oah.chat.agent import run_chat

    source = inspect.getsource(run_chat)
    assert "question_excerpt" not in source and "redacted_excerpt" not in source
    assert "question_sha256" in source and "question_chars" in source


# --- stdout -------------------------------------------------------------------------------------------------------------
def test_each_record_is_also_one_structured_json_line_on_stdout(log, capsys):
    audit.record("dispatch", kind="ccme-wqi-location", evidence_sha256="ab" * 32, n=1)
    audit.record("chat-result", status="answered", answer_sha256="cd" * 32)
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 2
    first, second = (json.loads(line) for line in lines)
    assert first["severity"] == "INFO" and first["message"] == audit.STDOUT_MESSAGE
    assert first["audit"]["event"] == "dispatch" and first["audit"]["evidence_sha256"] == "ab" * 32
    file_lines = [json.loads(text) for text in log.read_text(encoding="utf-8").splitlines()]
    assert first["audit"] == file_lines[0] and second["audit"] == file_lines[1]  # the same digest-only content, chain fields included


def test_stdout_holds_no_text_a_user_typed_and_no_key(log, capsys, monkeypatch):
    monkeypatch.setenv("OAH_API_KEY", "k" * 40)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-secret-value")
    question = "Please tell me about someone@example.org and the river near my house"
    audit.record("chat-dispatch", question_sha256=audit.text_digest(question), question_chars=len(question))
    out = capsys.readouterr().out
    assert "someone@example.org" not in out and "river near my house" not in out
    assert "k" * 40 not in out and "sk-ant-test-secret-value" not in out and "question_excerpt" not in out


def test_a_broken_stdout_never_stops_the_audit_write(log, monkeypatch):
    class _Broken:
        def write(self, _text):
            raise OSError("closed")

        def flush(self):
            raise OSError("closed")

    monkeypatch.setattr(audit.sys, "stdout", _Broken())
    audit.record("dispatch", n=1)
    assert audit.verify_chain(log) == (True, 1, None)


def test_non_ascii_content_is_written_as_ascii_json_on_stdout(log, capsys):
    audit.record("dispatch", country="GR", note="Ελλάδα")
    out = capsys.readouterr().out
    assert out.isascii() and json.loads(out.strip())["audit"]["note"] == "Ελλάδα"


# --- rotation cap ----------------------------------------------------------------------------------------------------
def _fill(count, filler=40):
    for index in range(count):
        audit.record("dispatch", n=index, filler="x" * filler)


def test_only_the_newest_rotated_files_are_kept_and_the_chain_still_verifies(log, monkeypatch):
    monkeypatch.setattr(audit, "MAX_LOG_BYTES", 300)
    monkeypatch.setattr(audit, "MAX_ROTATED_FILES", 3)
    _fill(40)
    rotated = audit.rotated_files(log)
    assert len(rotated) == 3  # the oldest were removed first
    stamps = [path.name for path in rotated]
    assert stamps == sorted(stamps)
    ok, total, where = audit.verify_all()
    assert ok is True and where is None and 0 < total < 40  # what remains verifies; the removed records are gone


def test_the_oldest_file_is_the_one_removed(log, monkeypatch):
    monkeypatch.setattr(audit, "MAX_LOG_BYTES", 300)
    monkeypatch.setattr(audit, "MAX_ROTATED_FILES", 2)
    _fill(20)
    numbers = []
    for path in audit.rotated_files(log) + [log]:
        numbers += [json.loads(text)["n"] for text in path.read_text(encoding="utf-8").splitlines()]
    assert numbers == sorted(numbers) and numbers[-1] == 19 and numbers[0] > 0  # the newest records survive, the first ones do not


def test_tampering_with_what_remains_is_still_detected(log, monkeypatch):
    monkeypatch.setattr(audit, "MAX_LOG_BYTES", 300)
    monkeypatch.setattr(audit, "MAX_ROTATED_FILES", 3)
    _fill(40)
    rotated = audit.rotated_files(log)
    first = rotated[0]  # the oldest kept file: its first record starts from a hash whose file was deleted
    text = first.read_text(encoding="utf-8")
    number = json.loads(text.splitlines()[0])["n"]
    first.write_text(text.replace(f'"n": {number}', '"n": 9999', 1), encoding="utf-8")
    assert audit.verify_all()[0] is False
    first.write_text(text, encoding="utf-8")
    assert audit.verify_all()[0] is True
    middle = rotated[1]
    lines = middle.read_text(encoding="utf-8").splitlines()
    middle.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")  # a record removed at the start of a later file
    assert audit.verify_all()[0] is False


def test_a_log_that_never_rotated_is_still_checked_from_the_start(log):
    _fill(4)
    lines = log.read_text(encoding="utf-8").splitlines()
    log.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")  # the first record removed: no pruning explains it
    assert audit.verify_all()[0] is False


def test_a_failure_to_delete_an_old_file_does_not_block_the_write(log, monkeypatch):
    monkeypatch.setattr(audit, "MAX_LOG_BYTES", 300)
    monkeypatch.setattr(audit, "MAX_ROTATED_FILES", 1)
    _fill(6)
    from pathlib import Path

    def _refuse(self, *args, **kwargs):
        raise OSError("read-only")

    monkeypatch.setattr(Path, "unlink", _refuse)
    _fill(6)  # more rotations, every deletion refused: the records are still written
    assert audit.verify_all()[0] is True


def test_the_default_cap_is_small_because_the_disk_may_be_memory():
    assert 1 <= audit.MAX_ROTATED_FILES <= 10
    assert audit.MAX_ROTATED_FILES * audit.MAX_LOG_BYTES <= 64 * 1024 * 1024
