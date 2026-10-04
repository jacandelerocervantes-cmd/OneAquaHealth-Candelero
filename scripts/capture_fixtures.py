"""Capture a small, labeled real-sandbox fixture set with GET requests only."""
from __future__ import annotations
import hashlib
import json
from oah.config import sandbox_url
from oah.ingest.sandbox_client import configured_client
from oah.paths import fixtures_real_path
from oah.timeutil import format_utc, utc_now

BASE = sandbox_url()

def write_fixture(resource: dict, truncated: bool = False, original_content_count: int | None = None) -> None:
    target = fixtures_real_path(f"{resource['resourceType']}-{resource['id']}.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(resource, indent=2).encode()
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(target)
    metadata = {"source_url": f"{BASE}/{resource['resourceType']}/{resource['id']}", "retrieval_date_utc": format_utc(utc_now()), "resource_type": resource["resourceType"], "chosen_id": resource["id"], "sha256": hashlib.sha256(encoded).hexdigest(), "origin": "real-sandbox"}
    if truncated:
        metadata["truncated"] = True
    if original_content_count is not None:
        metadata["original_content_count"] = original_content_count
    sidecar = target.with_suffix(".metadata.json")
    sidecar.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

def first(resources, predicate):
    return next(resource for page in resources for resource in page if predicate(resource))

def main() -> None:
    client = configured_client()
    observation_pages = list(client.pages("Observation"))
    selected = [
        client.get_resource("Observation", "Obs-Almyros-AluminiumDissolved-2013"),
        client.get_resource("Location", "Loc-Almyros"),
        first(observation_pages, lambda r: any("observation-health-measure-oah" in p for p in r.get("meta", {}).get("profile", []))),
        first(observation_pages, lambda r: r.get("code", {}).get("coding", [{}])[0].get("system") == "https://oneaquahealth.eu/air-parameters"),
        first(client.pages("Group"), lambda r: True),
        client.get_resource("Library", "Library-Almyros-FullResults"),
    ]
    original_content_count = len(selected[-1].get("content", []))
    selected[-1]["content"] = selected[-1].get("content", [])[:5]
    for resource in selected[:-1]:
        write_fixture(resource)
    write_fixture(selected[-1], truncated=True, original_content_count=original_content_count)
    print(f"Captured {len(selected)} real sandbox fixtures.")

if __name__ == "__main__":
    main()
