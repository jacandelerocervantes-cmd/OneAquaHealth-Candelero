"""River-network risk calculations.

Exported symbols:
    - build_river_graph
    - propagate_risk
"""

from oah.risk.river_graph import build_river_graph, propagate_risk
from oah.risk.demo_topology import (
    DECAY_PER_KM,
    INITIAL_RISK,
    SOURCE_SITE,
    SYNTHETIC_EDGES,
)

__all__ = [
    "build_river_graph",
    "propagate_risk",
    "SYNTHETIC_EDGES",
    "SOURCE_SITE",
    "INITIAL_RISK",
    "DECAY_PER_KM",
]
