"""Closed-form 1D advection-dispersion-decay results used to validate the river risk proxy.

Model: C_t + u C_x = D C_xx - k C, with velocity ``u`` (m/s), longitudinal dispersion ``D`` (m^2/s)
and first-order decay ``k`` (1/s). Nothing here models a real river; these are textbook solutions
(see docs/math_registry.md) used to state exactly what ``oah.risk.river_graph`` approximates.

* Steady continuous release at x = 0 into a semi-infinite reach, C(0) = C0. The bounded solution is
  ``C(x) = C0 * exp(-lambda * x)`` with ``lambda = (sqrt(u^2 + 4 k D) - u) / (2 D)``. It is written here
  in the numerically stable form ``lambda = 2 k / (u + sqrt(u^2 + 4 k D))``, which reduces to ``k / u``
  when D = 0. The proxy ``risk = exp(-decay_per_km * d_km)`` therefore equals the exact solution when
  ``decay_per_km = 1000 * k / u`` and dispersion is negligible.
* Instantaneous release of mass M into cross-section A:
  ``C(x, t) = M / (A sqrt(4 pi D t)) * exp(-(x - u t)^2 / (4 D t) - k t)``. Along the cloud centre
  (x = u t) the concentration falls as ``t^(-1/2) * exp(-k t)``: dispersive dilution that the proxy
  does not have.
"""
from __future__ import annotations

import math

SECONDS_PER_DAY = 86400.0
METRES_PER_KM = 1000.0


def _check(decay_rate_per_s: float, velocity_m_s: float, dispersion_m2_s: float = 0.0) -> None:
    if not velocity_m_s > 0.0:
        raise ValueError(f"velocity_m_s must be positive, got {velocity_m_s}.")
    if decay_rate_per_s < 0.0:
        raise ValueError(f"decay_rate_per_s must be non-negative, got {decay_rate_per_s}.")
    if dispersion_m2_s < 0.0:
        raise ValueError(f"dispersion_m2_s must be non-negative, got {dispersion_m2_s}.")


def effective_decay_per_km(decay_rate_per_s: float, velocity_m_s: float, dispersion_m2_s: float = 0.0) -> float:
    """Exact steady-state spatial decay rate (per km) of the advection-dispersion-decay equation."""
    _check(decay_rate_per_s, velocity_m_s, dispersion_m2_s)
    k, u, d = decay_rate_per_s, velocity_m_s, dispersion_m2_s
    return METRES_PER_KM * 2.0 * k / (u + math.sqrt(u * u + 4.0 * k * d))


def proxy_decay_per_km(decay_rate_per_s: float, velocity_m_s: float) -> float:
    """The ``decay_per_km`` that makes the proxy exact when dispersion is negligible: ``1000 k / u``."""
    _check(decay_rate_per_s, velocity_m_s)
    return METRES_PER_KM * decay_rate_per_s / velocity_m_s


def implied_decay_rate_per_day(decay_per_km: float, velocity_m_s: float) -> float:
    """Physical first-order decay rate (1/day) implied by a proxy ``decay_per_km`` at a given velocity."""
    if decay_per_km < 0.0:
        raise ValueError(f"decay_per_km must be non-negative, got {decay_per_km}.")
    _check(0.0, velocity_m_s)
    return decay_per_km / METRES_PER_KM * velocity_m_s * SECONDS_PER_DAY


def steady_state_ratio(distance_km: float, decay_rate_per_s: float, velocity_m_s: float, dispersion_m2_s: float = 0.0) -> float:
    """Exact C(x) / C0 for the steady continuous release."""
    if distance_km < 0.0:
        raise ValueError(f"distance_km must be non-negative, got {distance_km}.")
    return math.exp(-effective_decay_per_km(decay_rate_per_s, velocity_m_s, dispersion_m2_s) * distance_km)


def proxy_relative_error(distance_km: float, decay_rate_per_s: float, velocity_m_s: float, dispersion_m2_s: float) -> float:
    """``proxy / exact - 1`` for the steady release, with the proxy rate ``1000 k / u``.

    Never positive: dispersion slows the true decay, so the proxy UNDERESTIMATES downstream risk
    (anti-conservative) and the gap grows with distance and with ``k D / u^2``.
    """
    if distance_km < 0.0:
        raise ValueError(f"distance_km must be non-negative, got {distance_km}.")
    gap = proxy_decay_per_km(decay_rate_per_s, velocity_m_s) - effective_decay_per_km(
        decay_rate_per_s, velocity_m_s, dispersion_m2_s
    )
    return math.exp(-gap * distance_km) - 1.0


def pulse_concentration(
    distance_m: float, time_s: float, decay_rate_per_s: float, velocity_m_s: float, dispersion_m2_s: float,
    mass_per_area: float = 1.0,
) -> float:
    """Concentration of an instantaneous release (``mass_per_area`` = M / A) at ``distance_m`` and ``time_s``."""
    _check(decay_rate_per_s, velocity_m_s, dispersion_m2_s)
    if not (time_s > 0.0 and dispersion_m2_s > 0.0):
        raise ValueError("time_s and dispersion_m2_s must be positive for the pulse solution.")
    spread = 4.0 * dispersion_m2_s * time_s
    return (
        mass_per_area / math.sqrt(math.pi * spread)
        * math.exp(-((distance_m - velocity_m_s * time_s) ** 2) / spread - decay_rate_per_s * time_s)
    )


def pulse_centre_ratio(distance_km: float, reference_km: float, decay_rate_per_s: float, velocity_m_s: float) -> float:
    """Ratio of the cloud-centre concentration at ``distance_km`` to that at ``reference_km`` (pulse release).

    ``sqrt(reference / distance) * exp(-k (distance - reference) / u)``; the dispersion coefficient and the
    released mass cancel. The proxy predicts only the exponential factor, so for a pulse it OVERestimates
    the downstream centre concentration (conservative) by the factor ``sqrt(distance / reference)``.
    """
    _check(decay_rate_per_s, velocity_m_s)
    if not (distance_km > 0.0 and reference_km > 0.0):
        raise ValueError("distance_km and reference_km must be positive.")
    return math.sqrt(reference_km / distance_km) * math.exp(
        -decay_rate_per_s * (distance_km - reference_km) * METRES_PER_KM / velocity_m_s
    )
