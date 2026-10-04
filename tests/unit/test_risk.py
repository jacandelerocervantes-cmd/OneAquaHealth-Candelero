"""Tests for river-network risk propagation. All topologies here are illustrative and
synthetic (documented), never claims about real hydrology, even when a site id string
happens to reuse a real sandbox Location identifier as a label.
"""
from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from oah.risk.river_graph import build_river_graph, propagate_risk


# --- build_river_graph ---------------------------------------------------------------------


def test_empty_edges_raise():
    with pytest.raises(ValueError, match="must not be empty"):
        build_river_graph([])


def test_non_positive_distance_raises():
    with pytest.raises(ValueError, match="strictly positive"):
        build_river_graph([("A", "B", 0.0)])
    with pytest.raises(ValueError, match="strictly positive"):
        build_river_graph([("A", "B", -1.0)])


def test_cycle_raises():
    with pytest.raises(ValueError, match="acyclic"):
        build_river_graph([("A", "B", 1.0), ("B", "C", 1.0), ("C", "A", 1.0)])


def test_valid_chain_builds_with_distance_attribute():
    graph = build_river_graph([("A", "B", 2.0), ("B", "C", 3.0)])
    assert graph["A"]["B"]["distance_km"] == 2.0
    assert graph["B"]["C"]["distance_km"] == 3.0


# --- propagate_risk: hand-computed 4-node chain -------------------------------------------
#
# Chain A -> B (2 km) -> C (3 km) -> D (1 km). initial_risk = 1.0, decay_per_km = 0.1.
#   risk(A) = 1.0                              (source)
#   risk(B) = 1.0 * exp(-0.1 * 2)  = exp(-0.2) = 0.8187307530779818
#   risk(C) = 1.0 * exp(-0.1 * 5)  = exp(-0.5) = 0.6065306597126334
#   risk(D) = 1.0 * exp(-0.1 * 6)  = exp(-0.6) = 0.5488116360940264
# (computed independently with Python's math.exp for the test, not by re-reading the source)


def _chain_graph():
    return build_river_graph([("A", "B", 2.0), ("B", "C", 3.0), ("C", "D", 1.0)])


def test_hand_computed_chain_risk_values():
    graph = _chain_graph()
    risk = propagate_risk(graph, "A", initial_risk=1.0, decay_per_km=0.1)
    assert risk["A"] == pytest.approx(1.0)
    assert risk["B"] == pytest.approx(math.exp(-0.2), rel=1e-9)
    assert risk["C"] == pytest.approx(math.exp(-0.5), rel=1e-9)
    assert risk["D"] == pytest.approx(math.exp(-0.6), rel=1e-9)


def test_risk_at_source_equals_initial_risk_exactly():
    graph = _chain_graph()
    for initial_risk in (0.0, 0.37, 1.0):
        risk = propagate_risk(graph, "A", initial_risk=initial_risk, decay_per_km=0.2)
        assert risk["A"] == initial_risk


def test_risk_strictly_decreases_downstream_along_a_single_path():
    graph = _chain_graph()
    risk = propagate_risk(graph, "A", initial_risk=1.0, decay_per_km=0.1)
    assert risk["A"] > risk["B"] > risk["C"] > risk["D"] > 0.0


def test_disconnected_node_gets_zero_risk():
    graph = _chain_graph()
    graph.add_node("Isolated-Site")  # present in the graph, unreachable from A
    risk = propagate_risk(graph, "A", initial_risk=1.0, decay_per_km=0.1)
    assert risk["Isolated-Site"] == 0.0


def test_upstream_node_not_downstream_of_source_gets_zero_risk():
    # A site upstream of the source (e.g. B is downstream of A) must not receive risk
    # computed as if it were downstream; propagate_risk only follows directed edges forward.
    graph = _chain_graph()
    risk = propagate_risk(graph, "C", initial_risk=1.0, decay_per_km=0.1)
    assert risk["A"] == 0.0
    assert risk["B"] == 0.0
    assert risk["C"] == 1.0


# --- propagate_risk: multiple paths combine by MAXIMUM, hand-computed diamond -------------
#
# Diamond: A -> B (1 km), A -> C (1 km), B -> D (1 km), C -> D (5 km). initial_risk=1.0,
# decay_per_km=0.1.
#   via A-B-D: distance 2 km -> exp(-0.2) = 0.8187307530779818
#   via A-C-D: distance 6 km -> exp(-0.6) = 0.5488116360940264
#   risk(D) must be the MAXIMUM of the two paths: 0.8187307530779818


def test_multiple_paths_combine_by_taking_the_maximum():
    graph = build_river_graph(
        [("A", "B", 1.0), ("A", "C", 1.0), ("B", "D", 1.0), ("C", "D", 5.0)]
    )
    risk = propagate_risk(graph, "A", initial_risk=1.0, decay_per_km=0.1)
    expected_via_b = math.exp(-0.1 * 2.0)
    expected_via_c = math.exp(-0.1 * 6.0)
    assert expected_via_b > expected_via_c  # sanity check on the hand-computed example
    assert risk["D"] == pytest.approx(expected_via_b, rel=1e-9)


# --- propagate_risk: validation --------------------------------------------------------------


def test_unknown_source_site_raises():
    graph = _chain_graph()
    with pytest.raises(ValueError, match="not a node"):
        propagate_risk(graph, "Nonexistent", initial_risk=1.0, decay_per_km=0.1)


def test_initial_risk_out_of_range_raises():
    graph = _chain_graph()
    with pytest.raises(ValueError, match=r"\[0\.0, 1\.0\]"):
        propagate_risk(graph, "A", initial_risk=1.5, decay_per_km=0.1)
    with pytest.raises(ValueError, match=r"\[0\.0, 1\.0\]"):
        propagate_risk(graph, "A", initial_risk=-0.1, decay_per_km=0.1)


def test_negative_decay_raises():
    graph = _chain_graph()
    with pytest.raises(ValueError, match="non-negative"):
        propagate_risk(graph, "A", initial_risk=1.0, decay_per_km=-0.01)


# --- properties ------------------------------------------------------------------------------


@given(
    initial_risk=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    decay_per_km=st.floats(min_value=0.0, max_value=5.0, allow_nan=False),
    d1=st.floats(min_value=0.01, max_value=100.0, allow_nan=False),
    d2=st.floats(min_value=0.01, max_value=100.0, allow_nan=False),
)
@settings(max_examples=100)
def test_property_risk_never_increases_downstream_and_stays_in_bounds(
    initial_risk, decay_per_km, d1, d2
):
    graph = build_river_graph([("A", "B", d1), ("B", "C", d2)])
    risk = propagate_risk(graph, "A", initial_risk=initial_risk, decay_per_km=decay_per_km)
    assert risk["A"] == initial_risk
    assert 0.0 <= risk["B"] <= risk["A"] + 1e-12
    assert 0.0 <= risk["C"] <= risk["B"] + 1e-12
