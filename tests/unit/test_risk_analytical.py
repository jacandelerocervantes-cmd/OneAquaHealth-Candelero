"""Validation of the river risk proxy against 1D advection-dispersion-decay solutions.

Purely mathematical checks with illustrative parameters (not measured river values). The steady solution is
verified against an independent finite-difference solver; the pulse solution against a finite-difference
residual of the PDE itself.
"""
import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from oah.risk.analytical import (
    effective_decay_per_km,
    implied_decay_rate_per_day,
    proxy_decay_per_km,
    proxy_relative_error,
    pulse_centre_ratio,
    pulse_concentration,
    steady_state_ratio,
)
from oah.risk.river_graph import build_river_graph, propagate_risk


def _solve_steady_bvp(u, d, k, length_m, cells):
    """Central-difference solution of u C' = D C'' - k C on [0, L], C(0) = 1, C(L) = 0 (Thomas algorithm)."""
    h = length_m / cells
    n = cells - 1  # interior nodes
    lower = np.full(n, d / h**2 + u / (2 * h))   # coefficient of C[i-1]
    diag = np.full(n, -2 * d / h**2 - k)         # coefficient of C[i]
    upper = np.full(n, d / h**2 - u / (2 * h))   # coefficient of C[i+1]
    rhs = np.zeros(n)
    rhs[0] -= lower[0] * 1.0                     # boundary C(0) = 1
    for i in range(1, n):                        # forward elimination
        factor = lower[i] / diag[i - 1]
        diag[i] -= factor * upper[i - 1]
        rhs[i] -= factor * rhs[i - 1]
    solution = np.zeros(n)
    solution[-1] = rhs[-1] / diag[-1]
    for i in range(n - 2, -1, -1):
        solution[i] = (rhs[i] - upper[i] * solution[i + 1]) / diag[i]
    return h, np.concatenate(([1.0], solution, [0.0]))


@pytest.mark.parametrize(("u", "d", "k"), [(1.0, 100.0, 1e-3), (0.5, 20.0, 5e-4), (2.0, 300.0, 2e-3)])
def test_closed_form_steady_decay_matches_an_independent_numerical_solution(u, d, k):
    lam_per_m = effective_decay_per_km(k, u, d) / 1000.0
    length = 40.0 / lam_per_m  # far enough that C(L) = 0 is harmless
    h, numerical = _solve_steady_bvp(u, d, k, length, cells=8000)
    for fraction in (0.05, 0.1, 0.2, 0.3):
        node = int(round(fraction * length / h))
        exact = math.exp(-lam_per_m * node * h)
        assert numerical[node] == pytest.approx(exact, rel=2e-3)


def test_without_dispersion_the_effective_rate_is_k_over_u_and_the_proxy_is_exact():
    k, u = 4.5e-5, 0.3
    assert effective_decay_per_km(k, u, 0.0) == pytest.approx(proxy_decay_per_km(k, u))
    graph = build_river_graph([("A", "B", 2.0), ("B", "C", 3.5), ("C", "D", 1.5)])
    risk = propagate_risk(graph, "A", 1.0, proxy_decay_per_km(k, u))
    for node, distance in (("B", 2.0), ("C", 5.5), ("D", 7.0)):
        assert risk[node] == pytest.approx(steady_state_ratio(distance, k, u, 0.0), rel=1e-12)


def test_dispersion_makes_the_proxy_underestimate_by_a_computable_amount():
    k, u = 1e-3, 1.0
    for d, epsilon in ((10.0, 0.01), (100.0, 0.1), (1000.0, 1.0)):
        assert k * d / u**2 == pytest.approx(epsilon)
        ratio = effective_decay_per_km(k, u, d) / proxy_decay_per_km(k, u)
        assert ratio == pytest.approx((math.sqrt(1 + 4 * epsilon) - 1) / (2 * epsilon), rel=1e-12)
    # epsilon = 0.01: exponent gap 1.0 %; at 3 e-folds of proxy decay the risk is 2.9 % low
    x_km = 3.0 / proxy_decay_per_km(k, u)
    assert proxy_relative_error(x_km, k, u, 10.0) == pytest.approx(-0.0294, abs=5e-4)
    assert proxy_relative_error(x_km, k, u, 0.0) == 0.0


@given(
    st.floats(1e-6, 1e-2), st.floats(0.05, 3.0), st.floats(0.0, 500.0), st.floats(0.0, 100.0),
)
@settings(max_examples=200, deadline=None)
def test_proxy_never_overestimates_and_error_grows_with_distance_and_dispersion(k, u, d, x_km):
    error = proxy_relative_error(x_km, k, u, d)
    assert -1.0 <= error <= 1e-12
    assert proxy_relative_error(x_km + 5.0, k, u, d) <= error + 1e-12
    assert proxy_relative_error(x_km, k, u, d + 50.0) <= error + 1e-12
    assert 0.0 <= effective_decay_per_km(k, u, d) <= proxy_decay_per_km(k, u) + 1e-12


def test_the_pulse_solution_satisfies_the_partial_differential_equation():
    u, d, k = 0.4, 15.0, 2e-4
    x, t, dx, dt = 3000.0, 6000.0, 0.5, 0.5
    f = lambda xx, tt: pulse_concentration(xx, tt, k, u, d)  # noqa: E731
    c_t = (f(x, t + dt) - f(x, t - dt)) / (2 * dt)
    c_x = (f(x + dx, t) - f(x - dx, t)) / (2 * dx)
    c_xx = (f(x + dx, t) - 2 * f(x, t) + f(x - dx, t)) / dx**2
    residual = c_t + u * c_x - d * c_xx + k * f(x, t)
    scale = abs(c_t) + abs(u * c_x) + abs(d * c_xx) + abs(k * f(x, t))
    assert abs(residual) < 1e-5 * scale


def test_pulse_centre_ratio_matches_the_solution_and_shows_the_dilution_the_proxy_lacks():
    u, d, k = 0.4, 15.0, 2e-4
    near_km, far_km = 2.0, 8.0
    near = pulse_concentration(near_km * 1000.0, near_km * 1000.0 / u, k, u, d)
    far = pulse_concentration(far_km * 1000.0, far_km * 1000.0 / u, k, u, d)
    assert far / near == pytest.approx(pulse_centre_ratio(far_km, near_km, k, u), rel=1e-12)
    proxy = math.exp(-proxy_decay_per_km(k, u) * (far_km - near_km))
    assert far / near == pytest.approx(proxy * math.sqrt(near_km / far_km), rel=1e-12)
    assert far / near < proxy, "for a pulse the proxy is conservative (it ignores dispersive dilution)"


def test_implied_physical_decay_of_the_demo_setting():
    # DECAY_PER_KM = 0.15 in oah.risk.demo_topology at an assumed 0.3 m/s implies about 3.9 decays per day
    assert implied_decay_rate_per_day(0.15, 0.3) == pytest.approx(3.888)
    k_per_s = implied_decay_rate_per_day(0.15, 0.3) / 86400.0
    assert proxy_decay_per_km(k_per_s, 0.3) == pytest.approx(0.15)


@pytest.mark.parametrize(
    ("call", "match"),
    [
        (lambda: effective_decay_per_km(1e-3, 0.0), "velocity"),
        (lambda: effective_decay_per_km(-1.0, 1.0), "decay_rate"),
        (lambda: effective_decay_per_km(1e-3, 1.0, -1.0), "dispersion"),
        (lambda: steady_state_ratio(-1.0, 1e-3, 1.0), "distance"),
        (lambda: proxy_relative_error(-1.0, 1e-3, 1.0, 1.0), "distance"),
        (lambda: implied_decay_rate_per_day(-0.1, 1.0), "decay_per_km"),
        (lambda: pulse_concentration(10.0, 0.0, 1e-3, 1.0, 1.0), "positive"),
        (lambda: pulse_concentration(10.0, 5.0, 1e-3, 1.0, 0.0), "positive"),
        (lambda: pulse_centre_ratio(0.0, 1.0, 1e-3, 1.0), "positive"),
    ],
)
def test_invalid_inputs_are_rejected(call, match):
    with pytest.raises(ValueError, match=match):
        call()
