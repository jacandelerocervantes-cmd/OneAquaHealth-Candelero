"""A deterministic, best-effort check for causal claims about EXTERNAL context in a chat answer.

The prompt tells the model that weather, river flow and species records are context only and that "rainfall may be
relevant" is the strongest allowed statement. A prompt is not a control, so when an answer rests on an external tool
result, each sentence is also checked here: a sentence that names a weather or flow term (or a species term) AND a
water-quality term AND carries a causal cue ("caused", "due to", "because of", "led to", "explains", "contributed to",
"indicates", ...) is flagged ``unsupported-causal-claim`` and the answer is withheld like any other unsafe answer.

A cue preceded within a few words by a negation ("does not show that rain caused ...", "nothing here shows ...") is not
counted, so repeating the fixed notice does not trip it. The check is English only (it runs before any translation), a
regular-expression heuristic, and easy to evade with a rewording: it narrows the gap, it does not close it (see
docs/external_context.md section 9).
"""
from __future__ import annotations

import re

FLAG = "unsupported-causal-claim"

_WEATHER = re.compile(
    r"\b(?:rain\w*|precipitation|storms?|showers?|downpours?|flood\w*|runoff|weather|temperatures?|heat\w*|dry|drought|"
    r"discharge|flow\w*|river\s+levels?)\b",
    re.IGNORECASE,
)
_SPECIES = re.compile(
    r"\b(?:species|mayfl\w+|stonefl\w+|caddisfl\w+|ephemeroptera|plecoptera|trichoptera|odonata|dragonfl\w+|damselfl\w+|"
    r"chironomid\w*|midges?|gammarid\w*|shrimps?|mussels?|unionida|ept|macroinvertebrates?|gbif)\b",
    re.IGNORECASE,
)
_QUALITY = re.compile(
    r"\b(?:nitrates?|nitrites?|ammonium|ammonia|phosph\w+|oxygen|bod5?|cod|pollut\w+|contaminat\w+|water[- ]quality|quality|"
    r"concentrations?|exceed\w*|elevated|spikes?|increase\w*|decrease\w*|rise|rose|risen|fell|drop\w*|improv\w+|"
    r"deteriorat\w+|worse\w*|bloom\w*|turbidity|limits?|clean|healthy|poor|good)\b",
    re.IGNORECASE,
)
_CAUSAL = re.compile(
    r"\b(?:caus\w+|resulted?\s+in|results?\s+in|led\s+to|leads?\s+to|lead\s+to|due\s+to|because\s+of|owing\s+to|explains?|"
    r"explained|explaining|responsible\s+for|driven\s+by|triggered?|attributable\s+to|thanks\s+to|accounts?\s+for|"
    r"reason\s+for|contribut\w+\s+to)\b",
    re.IGNORECASE,
)
_INDICATES = re.compile(r"\b(?:indicat\w+|prove[sd]?|demonstrat\w+|confirm\w*|shows?\s+that|reveal\w*|signals?|reflects?)\b", re.IGNORECASE)
_NEGATION = re.compile(
    r"\b(?:not|no|never|nothing|cannot|can't|without|neither|nor|doesn't|don't|isn't|aren't|wasn't|weren't|won't|unable)\b",
    re.IGNORECASE,
)
_SENTENCES = re.compile(r"(?<=[.!?;:])\s+|\n+")
NEGATION_WINDOW = 40  # characters before the cue that may hold a negation


def _asserted(sentence: str, cues: re.Pattern[str]) -> bool:
    """Whether a cue of ``cues`` occurs in ``sentence`` without a negation just before it."""
    return any(not _NEGATION.search(sentence[max(0, match.start() - NEGATION_WINDOW) : match.start()]) for match in cues.finditer(sentence))


def causal_claim_flags(text: str) -> tuple[str, ...]:
    """``(FLAG,)`` when a sentence of ``text`` asserts that weather, flow or species records caused, explain or indicate water quality."""
    for sentence in _SENTENCES.split(text):
        if not _QUALITY.search(sentence):
            continue
        if _WEATHER.search(sentence) and _asserted(sentence, _CAUSAL):
            return (FLAG,)
        if _SPECIES.search(sentence) and (_asserted(sentence, _CAUSAL) or _asserted(sentence, _INDICATES)):
            return (FLAG,)
    return ()
