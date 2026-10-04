"""Small pure helpers for SUSHI build output."""
from __future__ import annotations
import json
import os
import re
import shutil
from pathlib import Path

def resource_counts(resources: list[dict]) -> dict[str, int]:
    return {kind: sum(item.get("resourceType") == kind for item in resources) for kind in ("StructureDefinition", "ValueSet", "CodeSystem")}

def load_resource_counts(directory: Path) -> dict[str, int]:
    return resource_counts([json.loads(file.read_text(encoding="utf-8")) for file in directory.glob("*.json")])

def sushi_totals(output: str) -> tuple[int, int] | None:
    match = re.search(r"(\d+)\s+Errors?\s+(\d+)\s+Warnings?", output)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)))

def find_sushi() -> str | None:
    names = ("sushi.cmd", "sushi.exe", "sushi") if os.name == "nt" else ("sushi",)
    return next((path for name in names if (path := shutil.which(name))), None)
