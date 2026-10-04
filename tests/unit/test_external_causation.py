"""The deterministic causal-claim check for answers that rest on external context (best effort, English)."""
from __future__ import annotations

import pytest

from oah.chat.causation import FLAG, causal_claim_flags


@pytest.mark.parametrize(
    "text",
    [
        "The heavy rainfall caused the nitrate increase in March.",
        "Nitrate was high because of the rain that month.",
        "Phosphate levels rose due to the storm.",
        "Rainfall explains the higher ammonium values.",
        "The flood led to poor water quality.",
        "High river discharge contributed to the nitrate spike.",
        "Higher temperature was responsible for the oxygen drop.",
        "The nitrate peak was driven by the heavy rain.",
        "The presence of mayflies indicates good water quality.",
        "Few stoneflies prove that the river is polluted.",
        "The absence of caddisflies shows that water quality is poor.",
        "Species records confirm the improvement of the water quality.",
        "Low flow resulted in an elevated phosphate concentration.",
        "Drought is the reason for the nitrate concentrations.",
    ],
)
def test_a_causal_or_indicator_claim_about_context_is_flagged(text: str) -> None:
    assert causal_claim_flags(text) == (FLAG,)


@pytest.mark.parametrize(
    "text",
    [
        "Rainfall may be relevant for the nitrate values in March.",
        "Rainfall in March 2021 was 10.1 mm and nitrate was 3 mg/L.",
        "This does not show that rain caused the nitrate increase.",
        "Nothing here shows that the flow caused any water-quality value.",
        "The weather context cannot explain the phosphate values.",
        "Species records are opportunistic and do not indicate good water quality.",
        "Weather data are partial due to the ERA5 delay.",  # a cause of missing data, not of a water-quality value
        "River discharge is modelled for the nearest river cell.",
        "The external provider was unavailable because of its call budget.",
        "No mayfly records were returned; that does not mean the species is absent.",
        "",
        "Nitrate exceeded the limit in 2021.",
    ],
)
def test_context_statements_and_negated_repeats_of_the_notice_are_not_flagged(text: str) -> None:
    assert causal_claim_flags(text) == ()


def test_only_the_offending_sentence_matters() -> None:
    answer = "Rainfall in March was 10.1 mm. Nitrate was 3 mg/L. The rain caused the nitrate to rise. Source: Open-Meteo."
    assert causal_claim_flags(answer) == (FLAG,)
    assert causal_claim_flags("Rainfall in March was 10.1 mm.\nThe nitrate was 3 mg/L in March.") == ()
