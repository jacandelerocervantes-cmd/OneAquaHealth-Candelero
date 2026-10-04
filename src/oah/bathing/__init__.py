"""EEA bathing-water classification slice (Bathing Water Directive, status of bathing water, 2025 v1.0).

Store build (``build.py``, command line ``scripts/build_bathing_water_store.py``), stdlib streaming xlsx reader
(``xlsx.py``), read-only reader (``store.py``) and the dictionaries the API and the chat tools return (``service.py``).
See ``docs/bathing_water_store.md``. Data from this package carries ``origin`` ``real-eea-bathing-water`` and is a
per-season CLASSIFICATION, never a concentration of E. coli or intestinal enterococci.
"""
