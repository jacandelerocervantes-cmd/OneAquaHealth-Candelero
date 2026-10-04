# Signing worksheet for the numeric limits

Optional for the hackathon (see `docs/limits_verification.md`). Generated 2026-09-29 from `oah.indices.limit_verification.current_limits()`. How to sign, who signs and what
a signature means: `docs/limits_verification.md`. **Nothing here is signed.** Each row below is a proposal: compare
the value with the PRIMARY text named in the evidence column, and only then paste the snippet into
`VERIFICATIONS` in `src/oah/indices/limit_verification.py`, filling your handle and the date, in a commit made by you.
If the value differs from the text, do not sign: correct the limit first (a signature is bound to the value).

Sourced limits: 27. Limits without a legal source (conventions): 4.

## Sourced limits

| Key | Value(s) | Unit | Compare with | What to see |
|---|---|---|---|---|
| `drinking\|-\|Aluminium dissolved` | 200 | ug/L | Directive (EU) 2020/2184, Annex I Part C, L 435/40 | row "Aluminium 200 ug/l" (indicator parameter) |
| `drinking\|-\|Ammonium` | 0.5 | mg/L | Directive (EU) 2020/2184, Annex I Part C, L 435/40 | row "Ammonium 0,50 mg/l" (indicator parameter) |
| `drinking\|-\|Arsenic dissolved` | 10 | ug/L | Directive (EU) 2020/2184, Annex I Part B, L 435/35 | row "Arsenic 10 ug/l" |
| `drinking\|-\|Cadmium dissolved` | 5 | ug/L | Directive (EU) 2020/2184, Annex I Part B, L 435/35 | row "Cadmium 5,0 ug/l" |
| `drinking\|-\|Conductivity` | 2500 | uS/cm | Directive (EU) 2020/2184, Annex I Part C, L 435/40 | row "Conductivity 2 500 uS cm-1 at 20 C" (indicator parameter) |
| `drinking\|-\|Copper dissolved` | 2000 | ug/L | Directive (EU) 2020/2184, Annex I Part B, L 435/36 | row "Copper 2,0 mg/l" (stored as 2000 ug/L) |
| `drinking\|-\|Electrical conductivity` | 2500 | uS/cm | Directive (EU) 2020/2184, Annex I Part C, L 435/40 | row "Conductivity 2 500 uS cm-1 at 20 C" (indicator parameter) |
| `drinking\|-\|Iron dissolved` | 200 | ug/L | Directive (EU) 2020/2184, Annex I Part C, L 435/40 | row "Iron 200 ug/l" (indicator parameter) |
| `drinking\|-\|Lead dissolved` | 10, 5 | ug/L | Directive (EU) 2020/2184, Annex I Part B, L 435/36 | row "Lead 5 ug/l" with the note 10 ug/l until 12 January 2036 (values are the current limit and the dated one) |
| `drinking\|-\|Mercury dissolved` | 1 | ug/L | Directive (EU) 2020/2184, Annex I Part B, L 435/36 | row "Mercury 1,0 ug/l" |
| `drinking\|-\|Nickel dissolved` | 20 | ug/L | Directive (EU) 2020/2184, Annex I Part B, L 435/36 | row "Nickel 20 ug/l" |
| `drinking\|-\|Nitrate` | 50 | mg/L | Directive (EU) 2020/2184, Annex I Part B, L 435/37 | row "Nitrate 50 mg/l" (as the ion) |
| `drinking\|-\|Nitrite` | 0.5 | mg/L | Directive (EU) 2020/2184, Annex I Part B, L 435/37 | row "Nitrite 0,50 mg/l" (as the ion) |
| `drinking\|-\|Sulphate` | 250 | mg/L | Directive (EU) 2020/2184, Annex I Part C, L 435/40 | row "Sulphate 250 mg/l" (indicator parameter) |
| `drinking\|-\|pH` | 6.5, 9.5 | pH | Directive (EU) 2020/2184, Annex I Part C, L 435/40 | row "Hydrogen ion concentration >= 6,5 and <= 9,5 pH units" |
| `surface\|-\|Lead dissolved` | 1.2 | ug/L | Directive 2013/39/EU, Annex II (Annex I Part A of 2008/105/EC), Table row (20), L 226/15 | AA-EQS inland surface waters "1,2 (13)"; footnote 13: bioavailable concentration |
| `surface\|-\|Mercury dissolved` | 0.07 | ug/L | Directive 2013/39/EU, Annex II (Annex I Part A of 2008/105/EC), Table row (21), L 226/15 | AA-EQS inland surface waters "0,07" |
| `surface\|-\|Nickel dissolved` | 4 | ug/L | Directive 2013/39/EU, Annex II (Annex I Part A of 2008/105/EC), Table row (23), L 226/15 | AA-EQS inland surface waters "4 (13)"; footnote 13: bioavailable concentration |
| `surface\|GR\|Ammonium` | 0.0772717 | mg/L | Skoulikidis et al., Water 2022, 14, 2738, Table 1 (HWQI), good/moderate boundary | N-NH4 0.06 mg/L as N, converted to mg/L as NH4 (x 1.288): 0.0773 |
| `surface\|GR\|Dissolved Oxygen` | 6.4 | mg/L | Skoulikidis et al., Water 2022, 14, 2738, Table 1 (HWQI), good/moderate boundary | DO good class 6.4-9 mg/L: minimum 6.4 |
| `surface\|GR\|Nitrate` | 2.65603 | mg/L | Skoulikidis et al., Water 2022, 14, 2738, Table 1 (HWQI), good/moderate boundary | N-NO3 0.60 mg/L as N, converted to mg/L as NO3 (x 4.427): 2.656 |
| `surface\|GR\|Nitrite` | 0.0262758 | mg/L | Skoulikidis et al., Water 2022, 14, 2738, Table 1 (HWQI), good/moderate boundary | N-NO2 8 ug/L as N, converted to mg/L as NO2 (x 3.284): 0.02628 |
| `surface\|GR\|Total phosphates` | 0.505912 | mg/L | Skoulikidis et al., Water 2022, 14, 2738, Table 1 (HWQI), good/moderate boundary | TP 165 ug/L as P, converted to mg/L as PO4 (x 3.066): 0.506 |
| `surface\|IT\|Ammonium` | 0.0772717 | mg/L | DM 8 November 2010 n. 260, Annex 1, Tab. 4.1.2/a (LIMeco), level 2, GU n. 30 of 7-2-2011, Suppl. ord. n. 31/L, p. 66 | N-NH4 0,06 mg/l as N, converted to mg/L as NH4 (x 1.288): 0.0773 |
| `surface\|IT\|Dissolved oxygen saturation deviation` | 20 | % | DM 8 November 2010 n. 260, Annex 1, Tab. 4.1.2/a (LIMeco), level 2, GU n. 30 of 7-2-2011, Suppl. ord. n. 31/L, p. 66 | |100 - % O2 saturation| <= 20 (level 2) |
| `surface\|IT\|Nitrate` | 5.31206 | mg/L | DM 8 November 2010 n. 260, Annex 1, Tab. 4.1.2/a (LIMeco), level 2, GU n. 30 of 7-2-2011, Suppl. ord. n. 31/L, p. 66 | N-NO3 1,2 mg/l as N, converted to mg/L as NO3 (x 4.427): 5.312 |
| `surface\|IT\|Total phosphates` | 0.306614 | mg/L | DM 8 November 2010 n. 260, Annex 1, Tab. 4.1.2/a (LIMeco), level 2, GU n. 30 of 7-2-2011, Suppl. ord. n. 31/L, p. 66 | total phosphorus 100 ug/l as P, converted to mg/L as PO4 (x 3.066): 0.3066 |

## Snippets to paste (fill `verified_by` and `verified_on`)

```python
VERIFICATIONS["drinking|-|Aluminium dissolved"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(200.0,), unit="ug/L",
    evidence="Directive (EU) 2020/2184, Annex I Part C, L 435/40; row "Aluminium 200 ug/l" (indicator parameter)",
)
VERIFICATIONS["drinking|-|Ammonium"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(0.5,), unit="mg/L",
    evidence="Directive (EU) 2020/2184, Annex I Part C, L 435/40; row "Ammonium 0,50 mg/l" (indicator parameter)",
)
VERIFICATIONS["drinking|-|Arsenic dissolved"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(10.0,), unit="ug/L",
    evidence="Directive (EU) 2020/2184, Annex I Part B, L 435/35; row "Arsenic 10 ug/l"",
)
VERIFICATIONS["drinking|-|Cadmium dissolved"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(5.0,), unit="ug/L",
    evidence="Directive (EU) 2020/2184, Annex I Part B, L 435/35; row "Cadmium 5,0 ug/l"",
)
VERIFICATIONS["drinking|-|Conductivity"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(2500.0,), unit="uS/cm",
    evidence="Directive (EU) 2020/2184, Annex I Part C, L 435/40; row "Conductivity 2 500 uS cm-1 at 20 C" (indicator parameter)",
)
VERIFICATIONS["drinking|-|Copper dissolved"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(2000.0,), unit="ug/L",
    evidence="Directive (EU) 2020/2184, Annex I Part B, L 435/36; row "Copper 2,0 mg/l" (stored as 2000 ug/L)",
)
VERIFICATIONS["drinking|-|Electrical conductivity"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(2500.0,), unit="uS/cm",
    evidence="Directive (EU) 2020/2184, Annex I Part C, L 435/40; row "Conductivity 2 500 uS cm-1 at 20 C" (indicator parameter)",
)
VERIFICATIONS["drinking|-|Iron dissolved"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(200.0,), unit="ug/L",
    evidence="Directive (EU) 2020/2184, Annex I Part C, L 435/40; row "Iron 200 ug/l" (indicator parameter)",
)
VERIFICATIONS["drinking|-|Lead dissolved"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(10.0, 5.0), unit="ug/L",
    evidence="Directive (EU) 2020/2184, Annex I Part B, L 435/36; row "Lead 5 ug/l" with the note 10 ug/l until 12 January 2036 (values are the current limit and the dated one)",
)
VERIFICATIONS["drinking|-|Mercury dissolved"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(1.0,), unit="ug/L",
    evidence="Directive (EU) 2020/2184, Annex I Part B, L 435/36; row "Mercury 1,0 ug/l"",
)
VERIFICATIONS["drinking|-|Nickel dissolved"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(20.0,), unit="ug/L",
    evidence="Directive (EU) 2020/2184, Annex I Part B, L 435/36; row "Nickel 20 ug/l"",
)
VERIFICATIONS["drinking|-|Nitrate"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(50.0,), unit="mg/L",
    evidence="Directive (EU) 2020/2184, Annex I Part B, L 435/37; row "Nitrate 50 mg/l" (as the ion)",
)
VERIFICATIONS["drinking|-|Nitrite"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(0.5,), unit="mg/L",
    evidence="Directive (EU) 2020/2184, Annex I Part B, L 435/37; row "Nitrite 0,50 mg/l" (as the ion)",
)
VERIFICATIONS["drinking|-|Sulphate"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(250.0,), unit="mg/L",
    evidence="Directive (EU) 2020/2184, Annex I Part C, L 435/40; row "Sulphate 250 mg/l" (indicator parameter)",
)
VERIFICATIONS["drinking|-|pH"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(6.5, 9.5), unit="pH",
    evidence="Directive (EU) 2020/2184, Annex I Part C, L 435/40; row "Hydrogen ion concentration >= 6,5 and <= 9,5 pH units"",
)
VERIFICATIONS["surface|-|Lead dissolved"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(1.2,), unit="ug/L",
    evidence="Directive 2013/39/EU, Annex II (Annex I Part A of 2008/105/EC), Table row (20), L 226/15; AA-EQS inland surface waters "1,2 (13)"; footnote 13: bioavailable concentration",
)
VERIFICATIONS["surface|-|Mercury dissolved"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(0.07,), unit="ug/L",
    evidence="Directive 2013/39/EU, Annex II (Annex I Part A of 2008/105/EC), Table row (21), L 226/15; AA-EQS inland surface waters "0,07"",
)
VERIFICATIONS["surface|-|Nickel dissolved"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(4.0,), unit="ug/L",
    evidence="Directive 2013/39/EU, Annex II (Annex I Part A of 2008/105/EC), Table row (23), L 226/15; AA-EQS inland surface waters "4 (13)"; footnote 13: bioavailable concentration",
)
VERIFICATIONS["surface|GR|Ammonium"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(0.07727173424147014,), unit="mg/L",
    evidence="Skoulikidis et al., Water 2022, 14, 2738, Table 1 (HWQI), good/moderate boundary; N-NH4 0.06 mg/L as N, converted to mg/L as NH4 (x 1.288): 0.0773",
)
VERIFICATIONS["surface|GR|Dissolved Oxygen"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(6.4,), unit="mg/L",
    evidence="Skoulikidis et al., Water 2022, 14, 2738, Table 1 (HWQI), good/moderate boundary; DO good class 6.4-9 mg/L: minimum 6.4",
)
VERIFICATIONS["surface|GR|Nitrate"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(2.6560303283428643,), unit="mg/L",
    evidence="Skoulikidis et al., Water 2022, 14, 2738, Table 1 (HWQI), good/moderate boundary; N-NO3 0.60 mg/L as N, converted to mg/L as NO3 (x 4.427): 2.656",
)
VERIFICATIONS["surface|GR|Nitrite"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(0.02627582514082546,), unit="mg/L",
    evidence="Skoulikidis et al., Water 2022, 14, 2738, Table 1 (HWQI), good/moderate boundary; N-NO2 8 ug/L as N, converted to mg/L as NO2 (x 3.284): 0.02628",
)
VERIFICATIONS["surface|GR|Total phosphates"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(0.50591241483679,), unit="mg/L",
    evidence="Skoulikidis et al., Water 2022, 14, 2738, Table 1 (HWQI), good/moderate boundary; TP 165 ug/L as P, converted to mg/L as PO4 (x 3.066): 0.506",
)
VERIFICATIONS["surface|IT|Ammonium"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(0.07727173424147014,), unit="mg/L",
    evidence="DM 8 November 2010 n. 260, Annex 1, Tab. 4.1.2/a (LIMeco), level 2, GU n. 30 of 7-2-2011, Suppl. ord. n. 31/L, p. 66; N-NH4 0,06 mg/l as N, converted to mg/L as NH4 (x 1.288): 0.0773",
)
VERIFICATIONS["surface|IT|Dissolved oxygen saturation deviation"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(20.0,), unit="%",
    evidence="DM 8 November 2010 n. 260, Annex 1, Tab. 4.1.2/a (LIMeco), level 2, GU n. 30 of 7-2-2011, Suppl. ord. n. 31/L, p. 66; |100 - % O2 saturation| <= 20 (level 2)",
)
VERIFICATIONS["surface|IT|Nitrate"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(5.312060656685729,), unit="mg/L",
    evidence="DM 8 November 2010 n. 260, Annex 1, Tab. 4.1.2/a (LIMeco), level 2, GU n. 30 of 7-2-2011, Suppl. ord. n. 31/L, p. 66; N-NO3 1,2 mg/l as N, converted to mg/L as NO3 (x 4.427): 5.312",
)
VERIFICATIONS["surface|IT|Total phosphates"] = Verification(
    verified_by="<your-handle>", verified_on="<YYYY-MM-DD>",
    values=(0.3066135847495697,), unit="mg/L",
    evidence="DM 8 November 2010 n. 260, Annex 1, Tab. 4.1.2/a (LIMeco), level 2, GU n. 30 of 7-2-2011, Suppl. ord. n. 31/L, p. 66; total phosphorus 100 ug/l as P, converted to mg/L as PO4 (x 3.066): 0.3066",
)
```

## Limits without a legal source

No legal source was found. It can be signed only as a project convention, or replaced by a sourced value first.

| Key | Value(s) | Unit | Basis shown in outputs |
|---|---|---|---|
| `drinking\|-\|Dissolved Oxygen` | 6 | mg/L | convention: project value, no legal source found |
| `drinking\|-\|Total phosphates` | 0.1 | mg/L | convention: project value, no legal source found |
| `drinking\|-\|Water temperature` | 25 | Cel | convention: project value, no legal source found |
| `drinking\|-\|Zinc dissolved` | 100 | ug/L | convention: project value, no legal source found |

The surface-regime rows for parameters without their own surface value (for example arsenic or copper on a river) reuse the drinking-water value and are labelled `proxy` in every output; they are signed, if at all, under the drinking-water row.
