"""Illustrative river-network risk propagation demo.

This is NOT real hydrology. The topology below is a small, explicitly documented synthetic
network that reuses real OneAquaHealth sandbox Location identifiers ONLY as convenient,
human-readable labels for a made-up demonstration graph -- it does not claim that these
sites are really connected this way, or with these distances, in the real world. Anyone
wanting real river topology must source it from a real hydrological dataset (e.g.
HydroRIVERS/HydroSHEDS) and pass it into build_river_graph themselves.
"""
from __future__ import annotations

from oah.paths import qc_report_path
from oah.risk.river_graph import build_river_graph, propagate_risk
from oah.risk.demo_topology import (
    DECAY_PER_KM,
    INITIAL_RISK,
    SOURCE_SITE,
    SYNTHETIC_EDGES,
)


def build_report(risk_by_node: dict[str, float]) -> str:
    lines = [
        "# River-Network Risk Propagation Report",
        "",
        "> [!IMPORTANT]",
        "> **SYNTHETIC / ILLUSTRATIVE: this topology is a documented example, not real",
        "> hydrology.** Site ids reuse real sandbox Location identifiers as labels only.",
        "",
        f"Source site: `{SOURCE_SITE}`  |  initial risk: {INITIAL_RISK}  |  "
        f"decay per km: {DECAY_PER_KM}",
        "",
        "| Site | Propagated risk |",
        "| --- | ---: |",
    ]
    for site, risk in sorted(risk_by_node.items(), key=lambda item: -item[1]):
        lines.append(f"| `{site}` | {risk:.4f} |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    graph = build_river_graph(SYNTHETIC_EDGES)
    risk_by_node = propagate_risk(graph, SOURCE_SITE, INITIAL_RISK, DECAY_PER_KM)
    report = build_report(risk_by_node)

    target = qc_report_path("risk_propagation_report.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report, encoding="utf-8")

    print(report)
    print(f"Report written to: {target}")


if __name__ == "__main__":
    main()
