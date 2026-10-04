"""Export CCME WQI results for real sandbox Locations as OAH-indicators FHIR Observations."""
from __future__ import annotations

import json

from oah.config import sandbox_url
from oah.fhir.output.export import build_indicators_bundle
from oah.indices.apply_to_sandbox import apply_ccme_wqi_to_sandbox
from oah.paths import export_path
from oah.timeutil import format_utc, utc_now


def main() -> None:
    result = apply_ccme_wqi_to_sandbox()
    bundle = build_indicators_bundle(result, format_utc(utc_now()), sandbox_url())
    target = export_path("indicators-bundle.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Input origin: real-sandbox")
    print(f"Evaluated locations exported: {result['evaluated_locations_count']}")
    print(f"Skipped locations (no Observation emitted): {result['skipped_locations_count']}")
    print(target)


if __name__ == "__main__":
    main()
