"""Run the OneAquaHealth API locally with uvicorn, for demo/manual use.

The user runs this, not an agent: it starts a long-lived server process.
"""
from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run("oah.api.app:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
