"""Privacy, k-anonymity, spatial generalization, and consent modules.

Exported symbols:
    - enforce_k_anonymity
    - generalize_coordinates
    - ConsentRecord
    - is_active
"""

from oah.privacy.consent import ConsentRecord, is_active
from oah.privacy.geo_generalization import generalize_coordinates
from oah.privacy.k_anonymity import enforce_k_anonymity

__all__ = [
    "ConsentRecord",
    "enforce_k_anonymity",
    "generalize_coordinates",
    "is_active",
]
