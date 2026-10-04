"""Measure the numeric-grounding check on the curated, generated and holdout adversarial sets."""
from __future__ import annotations

from oah.explain.grounding import check_grounding
from oah.explain.grounding_cases import all_cases, holdout_cases
from oah.paths import qc_report_path


def _rates(cases):
    valid = [c for c in cases if c[0] == "valid"]
    adversarial = [c for c in cases if c[0] == "adversarial"]
    rejected = [c for c in valid if not check_grounding(c[2], c[3]).grounded]
    missed = [c for c in adversarial if check_grounding(c[2], c[3]).grounded]
    return valid, adversarial, rejected, missed


def main() -> None:
    lines = [
        "# Numeric-grounding adversarial evaluation",
        "",
        "SYNTHETIC cases written by the project authors: this measures the check on those cases, not on real model output.",
        "",
        "| Set | Valid | False rejections | Adversarial | Missed | Detection |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, cases in (("curated + generated", all_cases()), ("holdout", holdout_cases())):
        valid, adversarial, rejected, missed = _rates(cases)
        detection = 1 - len(missed) / len(adversarial)
        lines.append(f"| {name} | {len(valid)} | {len(rejected)} ({len(rejected) / len(valid):.1%}) | {len(adversarial)} | {len(missed)} | {detection:.1%} |")
        for kind, group in (("FALSE REJECTION", rejected), ("MISSED", missed)):
            lines += [f"- {kind} [{c[1]}]: {c[2]}" for c in group]
    target = qc_report_path("grounding_eval_report.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[4:]))
    print(target)


if __name__ == "__main__":
    main()
