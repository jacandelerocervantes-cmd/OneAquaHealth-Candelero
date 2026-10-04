"""Container health probe: exit 0 when GET /health answers 200 on the port the server listens on.

Used by the image's HEALTHCHECK (the slim image has no curl). Cloud Run ignores HEALTHCHECK and uses the probes in
deploy/cloudrun.service.yaml; this one serves ``docker run`` and local checks. Standard library only.
"""
from __future__ import annotations

import os
import sys
import urllib.request


def main() -> int:
    port = os.environ.get("PORT", "8080")
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as response:  # noqa: S310 (fixed local URL)
            return 0 if response.status == 200 else 1
    except OSError:
        return 1


if __name__ == "__main__":
    sys.exit(main())
