"""A single shared, explicitly synthetic river-network topology used by both
scripts/eval_risk.py and the API's /risk endpoint, so the two never drift apart.

This is NOT real hydrology. See src/oah/risk/river_graph.py's module docstring for the
policy on why real topology is never invented here.
"""
from __future__ import annotations

SYNTHETIC_EDGES: list[tuple[str, str, float]] = [
    ("Loc-Almyros", "Loc-Almyros-Estuary", 3.5),
    ("Loc-Almyros-Estuary", "Loc-Almyros-Coast", 2.0),
    ("Loc-Nordre-Aker", "Loc-Almyros-Coast", 12.0),
]
SOURCE_SITE = "Loc-Almyros"
INITIAL_RISK = 1.0
# Illustrative only: at an assumed 0.3 m/s this implies about 3.9 decays per day (oah.risk.analytical).
DECAY_PER_KM = 0.15
