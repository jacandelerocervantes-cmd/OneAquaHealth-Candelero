"""Read-only classification of public-sandbox Observation identifiers."""
from __future__ import annotations

# Observed in the public sandbox; these prefixes are not published by the consortium.
OFFICIAL_OBSERVATION_PREFIXES = (
    "Obs-Almyros-",
    "Obs-Benevento",
    "Obs-BN-",
    "Obs-OS-",
    "Obs-WaterTemp-",
    "Obs-EC-",
)


def classify_observation(observation: dict) -> str:
    """Classify an Observation as an official-looking or other sandbox record."""
    identifier = observation.get("id", "")
    if isinstance(identifier, str) and identifier.startswith(OFFICIAL_OBSERVATION_PREFIXES):
        return "official"
    return "other"
