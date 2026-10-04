"""River-network risk propagation over an explicit, caller-supplied directed graph.

This module does NOT model real hydrology. It builds a directed acyclic graph from an
explicit list of (upstream_site_id, downstream_site_id, distance_km) edges that the caller
must supply; no real river topology is invented or looked up here. Site ids may reuse real
OneAquaHealth sandbox Location identifiers as labels only (the same convention used by the
synthetic campaign generator in oah.synthetic.campaign), never as a claim about actual
upstream/downstream relationships between those real sites unless the caller has verified
that relationship from a real hydrological source.

Risk propagation model:
    Risk only flows downstream along directed edges. Along a single path with total distance
    d_km from the source, risk decays as:

        risk(path) = initial_risk * exp(-decay_per_km * d_km)

    When a node is reachable from the source by more than one path, this module takes the
    MAXIMUM risk over all paths (not an average), as a documented precautionary-principle
    choice: averaging risk over multiple contamination paths could dilute a genuine risk
    from one path with a low-risk estimate from another, understating danger. A node not
    reachable from the source receives risk 0.0.

Relation to physics (validated in oah.risk.analytical, docs/math_registry.md): with
decay_per_km = 1000 * k / u this equals the steady advection-decay solution and is exact when
dispersion is negligible; dispersion makes it underestimate downstream risk, and for a pulse release
it overestimates the cloud-centre concentration (it lacks dispersive dilution).
"""

from __future__ import annotations

import math
from typing import Sequence

import networkx as nx


def build_river_graph(edges: Sequence[tuple[str, str, float]]) -> nx.DiGraph:
    """Build a directed acyclic river-network graph from explicit edges.

    Args:
        edges: Sequence of (upstream_site_id, downstream_site_id, distance_km) triples.
            distance_km must be strictly positive.

    Returns:
        A networkx.DiGraph with a "distance_km" edge attribute.

    Raises:
        ValueError: If edges is empty, any distance_km is not strictly positive, or the
            resulting graph contains a cycle (river networks are acyclic by construction;
            a cycle indicates a data error in the supplied edge list).
    """
    if not edges:
        raise ValueError("edges must not be empty.")

    graph = nx.DiGraph()
    for upstream_id, downstream_id, distance_km in edges:
        if not upstream_id or not downstream_id:
            raise ValueError(f"edge site ids must be non-empty: {(upstream_id, downstream_id)!r}")
        if distance_km <= 0.0:
            raise ValueError(
                f"distance_km must be strictly positive, got {distance_km} for edge "
                f"{upstream_id!r} -> {downstream_id!r}."
            )
        graph.add_edge(upstream_id, downstream_id, distance_km=float(distance_km))

    if not nx.is_directed_acyclic_graph(graph):
        cycle = nx.find_cycle(graph)
        raise ValueError(f"river network graph must be acyclic; found a cycle: {cycle}")

    return graph


def propagate_risk(
    graph: nx.DiGraph,
    source_site_id: str,
    initial_risk: float,
    decay_per_km: float,
) -> dict[str, float]:
    """Propagate a risk value downstream from a source site through a river-network graph.

    Args:
        graph: A DAG built by build_river_graph (or any networkx.DiGraph with a
            "distance_km" edge attribute and no cycles).
        source_site_id: The node where the risk originates. Must be a node in graph.
        initial_risk: Risk value at the source, in [0.0, 1.0].
        decay_per_km: Non-negative decay rate applied per kilometre of travel distance.

    Returns:
        A dict mapping every node in graph to its propagated risk. The source maps to
        initial_risk exactly. A node reachable from the source by one or more paths maps to
        the MAXIMUM decayed risk over those paths (see module docstring). A node not
        reachable from the source maps to 0.0.

    Raises:
        ValueError: If source_site_id is not a node in graph, if initial_risk is not in
            [0.0, 1.0], if decay_per_km is negative, or if graph contains a cycle.
    """
    if source_site_id not in graph:
        raise ValueError(f"source_site_id {source_site_id!r} is not a node in the graph.")
    if not 0.0 <= initial_risk <= 1.0:
        raise ValueError(f"initial_risk must be in [0.0, 1.0], got {initial_risk}.")
    if decay_per_km < 0.0:
        raise ValueError(f"decay_per_km must be non-negative, got {decay_per_km}.")
    if not nx.is_directed_acyclic_graph(graph):
        cycle = nx.find_cycle(graph)
        raise ValueError(f"river network graph must be acyclic; found a cycle: {cycle}")

    risk_by_node: dict[str, float] = {node: 0.0 for node in graph.nodes}
    risk_by_node[source_site_id] = float(initial_risk)

    descendants = nx.descendants(graph, source_site_id)
    for target in descendants:
        best_risk = 0.0
        for path in nx.all_simple_paths(graph, source_site_id, target):
            total_distance_km = sum(
                graph[path[i]][path[i + 1]]["distance_km"] for i in range(len(path) - 1)
            )
            path_risk = initial_risk * math.exp(-decay_per_km * total_distance_km)
            best_risk = max(best_risk, path_risk)
        risk_by_node[target] = best_risk

    return risk_by_node
