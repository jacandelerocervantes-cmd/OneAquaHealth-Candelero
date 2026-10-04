"""Prompt-injection and output-safety controls for the LLM explanation layer.

Threat model. The model only ever sees an EVIDENCE JSON built by this project from computed results, so a caller
cannot type free text into the prompt. But some strings in that evidence originate outside the project (a sandbox
resource id, a location reference, a code display, a note), and a hostile or corrupted sandbox record could carry
instructions ("indirect prompt injection"). Controls, in layers, none of them sufficient alone:

1. ``sanitize_evidence`` normalises every string and key, removes control and invisible characters, caps lengths,
   depth and size, and replaces instruction-like text and URLs before the prompt is built.
2. The system prompts say the EVIDENCE block is untrusted data, and the block is delimited so the payload cannot
   close it (see ``oah.explain.prompts``).
3. ``guard_output`` flags outputs that look hijacked or unsafe to render (URLs, HTML, links, code blocks, leaked
   instructions, an ``assess`` answer that does not follow the required format, excessive length).
4. The number and unit check in ``oah.explain.grounding`` flags invented figures.

What this does NOT do: pattern lists cannot stop a determined attacker with novel wording, and no deterministic check
can prove a model did not follow an injected instruction. The residual risk is measured by the adversarial harness in
``tests/unit/test_explain_safety.py`` (authored payloads) and stated in docs/security_review.md.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

MAX_STRING_CHARS = 200
MAX_KEY_CHARS = 64
MAX_DEPTH = 8
MAX_ITEMS = 200
MAX_TOTAL_CHARS = 20_000
MAX_OUTPUT_CHARS = 3_000
REMOVED = "[removed: instruction-like text]"
URL_REMOVED = "[url removed]"

# A scheme counts only when text follows the colon directly ("data:text/html", "https://x"): the plain words "data:" or
# "file:" before a space ("Available data: water chemistry") are ordinary prose, not a link (found in the first live
# web chat run, 2026-10-04, where it withheld a correct answer).
_URL = re.compile(r"(?i)\b(?:https?|ftp|file|data|javascript):[^\s]+|\bwww\.[^\s]+")
_INSTRUCTION = re.compile(
    r"(?is)"
    r"\b(?:ignore|disregard|forget|override|bypass)\b[^.\n]{0,60}\b(?:previous|prior|above|earlier|all|any|the|these|your)\b[^.\n]{0,30}\b(?:instruction|prompt|rule|message|context|guideline)s?\b"
    r"|\b(?:system|developer)\s*(?:prompt|message|instruction)s?\b"
    r"|\byou\s+are\s+(?:now|no\s+longer)\b"
    r"|\b(?:act|behave|respond)\s+as\b"
    r"|\bpretend\s+(?:to|you)\b"
    r"|\bnew\s+instructions?\b"
    r"|\bfrom\s+now\s+on\b"
    r"|\b(?:reveal|repeat|print|show)\b[^.\n]{0,30}\b(?:instructions?|prompt|system)\b"
    r"|(?:^|\W)(?:system|assistant|user|human|developer)\s*:"
    r"|<\s*/?\s*(?:system|assistant|user|evidence|instructions?)\b"
    r"|<\||\|>|\[/?inst\]|```|###\s*(?:instruction|system)"
)
# The sandbox comes from European partners and reviewers write in Spanish: the same instruction-override idea in the
# other common languages. This is a short list, not a translation of every phrasing; the rest is a measured gap.
_INSTRUCTION_OTHER_LANGUAGES = re.compile(
    r"(?is)"
    r"\b(?:ignora|ignore|olvida|omite|oublie|dimentica|ignoriere|vergiss)\b[^.\n]{0,60}"
    r"\b(?:instructions?|instrucciones|indicaciones|reglas|consignes|istruzioni|anweisungen|instruktionen|instrucoes|instru\u00e7\u00f5es)\b"
    r"|\b(?:nuevas?\s+instrucciones|nouvelles\s+instructions|nuove\s+istruzioni|neue\s+anweisungen)\b"
    r"|\beres\s+ahora\b|\bahora\s+eres\b|\btu\s+es\s+maintenant\b|\bdu\s+bist\s+jetzt\b"
)


def _looks_like_instruction(text: str) -> bool:
    return bool(_INSTRUCTION.search(text) or _INSTRUCTION_OTHER_LANGUAGES.search(text))


_SAFE_KEY = re.compile(r"[^\w\-. /]")

# Markup guard (docs/chat_agent.md, section 4): ANY "<" followed by a letter (any script), "/", "!" or "?" opens a tag, a
# closing tag, a comment, a doctype or a processing instruction, whatever the tag name (an allow-list of names always leaves
# <details>, <button>, <video>, <math>, <template> and the rest open). It also covers the "<url>" and "<mailto:...>" autolink
# forms. Scientific text is not touched: "<" before a digit, a space, "=" or a sign ("below <5 mg/L", "x < y", "<=") is fine.
_HTML = re.compile(r"<(?:[^\W\d_]|[/!?])")
# Markdown links in every form: inline "[text](target)" and image "![alt](target)", reference "[text][ref]" and "![alt][ref]",
# a bare image "![alt]", and a reference definition "[ref]: target" at the start of a line. A plain bracketed number such as "[1]"
# or "[mg/L]" followed by a space is not a link.
_MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\][(\[]|!\[[^\]]*\]|(?m:^[ \t]*\[[^\]]+\]:[ \t]*\S)")
# Health, potability or diagnostic claims are outside what these findings can support (English, Spanish, Italian).
_HEALTH_CLAIM = re.compile(
    r"(?i)\b(?:non-?potable|potable|drinkable|potabile|potabilidad)\b"
    r"|\b(?:safe|unsafe|fit|unfit|suitable|unsuitable)\s+(?:to|for)\s+(?:drink|drinking|human\s+consumption|consumption|swim|swimming|bath|bathing)\b"
    r"|\b(?:is|are|was|were)\s+(?:not\s+)?(?:safe|unsafe|toxic|harmful)\b"
    r"|\bcontaminated\b"
    r"|\bdiagnos(?:e|es|ed|is|tic)\b"
    r"|\bhealth\s+(?:risk|hazard|threat)s?\b"
    r"|\bcauses?\s+(?:illness|disease|infection|poisoning)\b"
    r"|\b(?:segur[oa]|apt[oa])\s+para\s+(?:beber|el\s+consumo|consumo)\b"
)
# Flags for which the text must not be rendered to a reader (the explanation routes return the text anyway and mark
# it unsafe; the chat route withholds it).
UNSAFE_OUTPUT_FLAGS = frozenset(
    {"contains-url", "contains-html", "contains-markdown-link", "contains-code-block", "leaks-instructions", "unsupported-health-claim"}
)
_CONCERN_LINE =re.compile(r"(?i)^\W*concern\s+level:\W*(?:low|moderate|high|critical)\b")


def _clean_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value)
    text = "".join(" " if ch.isspace() else ch for ch in text if unicodedata.category(ch) not in {"Cc", "Cf", "Cs", "Co"} or ch.isspace())
    return re.sub(r" {2,}", " ", text).strip()


def _sanitize_string(value: str, path: str, notes: list[str]) -> str:
    if any(unicodedata.category(ch) in {"Cc", "Cf"} and not ch.isspace() for ch in value):
        notes.append(f"{path}: control or invisible characters removed")
    text = _clean_text(value)
    if _looks_like_instruction(text):
        notes.append(f"{path}: instruction-like text removed")
        return REMOVED
    if _URL.search(text):
        notes.append(f"{path}: url removed")
        text = _URL.sub(URL_REMOVED, text)
    if len(text) > MAX_STRING_CHARS:
        notes.append(f"{path}: truncated from {len(text)} to {MAX_STRING_CHARS} characters")
        text = text[:MAX_STRING_CHARS]
    return text


def _sanitize_key(key: Any, path: str, notes: list[str], index: int) -> str:
    text = _clean_text(str(key))
    if _looks_like_instruction(text) or _URL.search(text):
        notes.append(f"{path}: key removed")
        return f"removed_key_{index}"
    cleaned = _SAFE_KEY.sub("", text)[:MAX_KEY_CHARS]
    return cleaned or f"key_{index}"


def _walk(node: Any, path: str, depth: int, notes: list[str]) -> Any:
    if depth > MAX_DEPTH:
        raise ValueError(f"Evidence is nested deeper than {MAX_DEPTH} levels at {path}.")
    if isinstance(node, str):
        return _sanitize_string(node, path, notes)
    if isinstance(node, bool) or node is None or isinstance(node, (int, float)):
        return node
    if isinstance(node, Mapping):
        if len(node) > MAX_ITEMS:
            raise ValueError(f"Evidence object at {path} has more than {MAX_ITEMS} entries.")
        clean: dict[str, Any] = {}
        for index, (key, value) in enumerate(node.items()):
            safe_key = _sanitize_key(key, f"{path}.{key}"[:80], notes, index)
            while safe_key in clean:
                safe_key += "_"
            clean[safe_key] = _walk(value, f"{path}.{safe_key}", depth + 1, notes)
        return clean
    if isinstance(node, (list, tuple, set)):
        items = list(node)
        if len(items) > MAX_ITEMS:
            raise ValueError(f"Evidence list at {path} has more than {MAX_ITEMS} items.")
        return [_walk(item, f"{path}[{i}]", depth + 1, notes) for i, item in enumerate(items)]
    notes.append(f"{path}: unsupported type {type(node).__name__} converted to text")
    return _sanitize_string(str(node), path, notes)


def sanitize_evidence(evidence: Mapping[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Return a sanitised copy of ``evidence`` and a tuple of notes describing every change.

    Raises ``ValueError`` when the evidence is too deep, has too many entries or is larger than ``MAX_TOTAL_CHARS``
    once serialised: such input is refused rather than truncated silently.
    """
    notes: list[str] = []
    clean = _walk(dict(evidence), "evidence", 0, notes)
    if len(json.dumps(clean, sort_keys=True)) > MAX_TOTAL_CHARS:
        raise ValueError(f"Evidence is larger than {MAX_TOTAL_CHARS} characters.")
    return clean, tuple(notes)


def sanitize_text(text: str, max_chars: int, *, remove_instructions: bool) -> tuple[str, tuple[str, ...]]:
    """Clean one free-text string (a chat message or history turn) and describe every change.

    Control and invisible characters are removed, URLs replaced and the text cut at ``max_chars``. With
    ``remove_instructions`` an instruction-like text is replaced entirely (used for untrusted history turns); without
    it the text is kept and the note ``instruction-like text present`` is returned instead (used for the user's own
    question, which must not be erased, but is only ever shown to the model as delimited data).
    """
    notes: list[str] = []
    if any(unicodedata.category(ch) in {"Cc", "Cf"} and not ch.isspace() for ch in text):
        notes.append("control or invisible characters removed")
    cleaned = _clean_text(text)
    if _looks_like_instruction(cleaned):
        if remove_instructions:
            return REMOVED, (*notes, "instruction-like text removed")
        notes.append("instruction-like text present")
    if _URL.search(cleaned):
        notes.append("url removed")
        cleaned = _URL.sub(URL_REMOVED, cleaned)
    if len(cleaned) > max_chars:
        notes.append(f"truncated from {len(cleaned)} to {max_chars} characters")
        cleaned = cleaned[:max_chars]
    return cleaned, tuple(notes)


def _shingles(text: str, size: int = 6) -> set[str]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {" ".join(words[i : i + size]) for i in range(max(0, len(words) - size + 1))}


def guard_output(
    text: str, mode: str, instructions: Sequence[str | tuple[str, int]], *, shingle_size: int = 6
) -> tuple[str, ...]:
    """Flags for model output that looks hijacked or unsafe to render. The text itself is never altered.

    ``leaks-instructions`` means the text shares a run of ``shingle_size`` consecutive words with an instruction text. An
    entry of ``instructions`` may be a ``(text, size)`` pair to use its own run length (the chat does).
    """
    flags: list[str] = []
    folded = unicodedata.normalize("NFKC", text)  # a fullwidth "<" or "[" is caught as well as the ASCII one
    if _URL.search(text) or _URL.search(folded):
        flags.append("contains-url")
    if _HTML.search(text) or _HTML.search(folded):
        flags.append("contains-html")
    if _MARKDOWN_LINK.search(text) or _MARKDOWN_LINK.search(folded):
        flags.append("contains-markdown-link")
    if "```" in text:
        flags.append("contains-code-block")
    for entry in instructions:
        prompt, size = (entry, shingle_size) if isinstance(entry, str) else entry
        if _shingles(text, size) & _shingles(prompt, size):
            flags.append("leaks-instructions")
            break
    if _HEALTH_CLAIM.search(text):
        flags.append("unsupported-health-claim")
    if len(text) > MAX_OUTPUT_CHARS:
        flags.append("too-long")
    if mode == "assess":
        first = next((line for line in text.splitlines() if line.strip()), "")
        if not _CONCERN_LINE.match(first):
            flags.append("assess-format-violation")
    return tuple(flags)
