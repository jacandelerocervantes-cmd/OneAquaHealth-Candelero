"""Read-only, retrying client for the public OAH FHIR sandbox."""
from __future__ import annotations
import json
import hashlib
import time
from typing import Any, Iterator
from urllib.parse import urlparse
import httpx
from oah.config import sandbox_url
from oah.paths import sandbox_snapshot_path
from oah.timeutil import format_utc, utc_now

MAX_PAGES = 200
MAX_RESOURCES = 100_000
MAX_RESPONSE_BYTES = 25 * 1024 * 1024


class SandboxClient:
    base_url: str
    timeout_seconds: float = 20.0
    retries: int = 3
    failure_limit: int = 3
    cooldown_seconds: float = 30.0
    def __init__(self, base_url: str, timeout_seconds: float = 20.0, retries: int = 3,
                 failure_limit: int = 3, cooldown_seconds: float = 30.0) -> None:
        self.base_url, self.timeout_seconds, self.retries = base_url, timeout_seconds, retries
        self.failure_limit, self.cooldown_seconds = failure_limit, cooldown_seconds
        self._failures, self._opened_at = 0, 0.0

    def _request(self, url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        if self._failures >= self.failure_limit and time.monotonic() - self._opened_at < self.cooldown_seconds:
            raise RuntimeError("Sandbox circuit breaker is open.")
        for attempt in range(self.retries + 1):
            try:
                response = httpx.get(url, params=params, timeout=self.timeout_seconds, headers={"Accept": "application/fhir+json"})
                response.raise_for_status()
                if len(response.content) > MAX_RESPONSE_BYTES:
                    raise RuntimeError("Sandbox response exceeds the size limit.")
                payload = response.json()
                if not isinstance(payload, dict):
                    raise RuntimeError("Sandbox response is not a JSON object.")
                self._failures = 0
                return payload
            except (httpx.HTTPError, ValueError):
                if attempt == self.retries:
                    self._failures += 1
                    self._opened_at = time.monotonic()
                    raise
                time.sleep(0.25 * (2**attempt))
        raise AssertionError("unreachable")

    def pages(self, resource_type: str, page_size: int = 100) -> Iterator[list[dict[str, Any]]]:
        if not resource_type.isascii() or not resource_type.isalpha():
            raise ValueError("resource_type must contain letters only.")
        url = f"{self.base_url.rstrip('/')}/{resource_type}"
        params: dict[str, str] | None = {"_count": str(page_size)}
        seen_urls: set[str] = set()
        pages_read = resources_read = 0
        while url:
            if url in seen_urls or pages_read >= MAX_PAGES:
                raise RuntimeError("Sandbox paging does not terminate (repeated link or page limit reached).")
            seen_urls.add(url)
            bundle = self._request(url, params)
            params = None
            # Entries without a resource (for example a search outcome) carry nothing to read and are skipped.
            resources = [
                entry["resource"]
                for entry in bundle.get("entry", [])
                if isinstance(entry, dict) and isinstance(entry.get("resource"), dict)
            ]
            pages_read += 1
            resources_read += len(resources)
            if resources_read > MAX_RESOURCES:
                raise RuntimeError("Sandbox returned more resources than the limit.")
            yield resources
            url = next((link["url"] for link in bundle.get("link", []) if link.get("relation") == "next"), "")
            if url:
                base, candidate = urlparse(self.base_url), urlparse(url)
                if (candidate.scheme, candidate.netloc) != (base.scheme, base.netloc):
                    raise RuntimeError("Sandbox next link changes origin.")
                base_path = base.path.rstrip("/")
                if candidate.path != base_path and not candidate.path.startswith(base_path + "/"):
                    raise RuntimeError("Sandbox next link escapes base path.")

    def get_resource(self, resource_type: str, resource_id: str) -> dict[str, Any]:
        if not resource_type.isascii() or not resource_type.isalpha() or not resource_id:
            raise ValueError("resource_type and resource_id must be non-empty valid values.")
        # Defense in depth: resource_id becomes a URL path segment. FHIR ids are restricted
        # to [A-Za-z0-9\-.]; reject anything else (slashes, "..", whitespace, control
        # characters) before it ever reaches an f-string, even though no caller currently
        # passes untrusted input here.
        if not all(char.isalnum() or char in "-." for char in resource_id):
            raise ValueError(f"resource_id contains characters outside the FHIR id charset: {resource_id!r}")
        return self._request(f"{self.base_url.rstrip('/')}/{resource_type}/{resource_id}")

    def snapshot(self, resource_type: str):
        target = sandbox_snapshot_path(resource_type)
        target.parent.mkdir(parents=True, exist_ok=True)
        resources = [resource for page in self.pages(resource_type) for resource in page]
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(resources, indent=2), encoding="utf-8")
        temporary.replace(target)
        metadata = {"source_url": self.base_url, "retrieval_date_utc": format_utc(utc_now()), "resource_type": resource_type, "count": len(resources), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "origin": "real-sandbox"}
        metadata_target = target.with_suffix(".metadata.json")
        metadata_temporary = metadata_target.with_suffix(".tmp")
        metadata_temporary.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        metadata_temporary.replace(metadata_target)
        return target

def configured_client() -> SandboxClient:
    return SandboxClient(sandbox_url())
