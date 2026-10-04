"""Write the API's OpenAPI schema to the committed file (docs/openapi.json), for generated client types.

Usage: ``python scripts/export_openapi.py`` to rewrite it, ``--check`` to fail when it is out of date.
The schema is built in-process (``app.openapi()``); no server is started and no network is used.
"""
from __future__ import annotations

import json
import sys

from oah.api.app import app
from oah.paths import openapi_path


def render() -> str:
    """The canonical text of the schema (sorted keys, two-space indent, trailing newline)."""
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    target = openapi_path()
    text = render()
    if "--check" in argv:
        current = target.read_text(encoding="utf-8") if target.is_file() else ""
        if current != text:
            print(f"{target.name} is out of date: run scripts/export_openapi.py")
            return 1
        print(f"{target.name} is up to date")
        return 0
    target.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {target.name} ({len(text)} characters)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
