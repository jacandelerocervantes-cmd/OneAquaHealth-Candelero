import hashlib
import json
import pytest
import httpx
from oah.ingest import sandbox_client

BASE = "https://sandbox.hl7europe.eu/oneaquahealth/fhir"

class Response:
    def __init__(self, body): self.body = body
    def raise_for_status(self): pass
    def json(self): return self.body
    @property
    def content(self): return json.dumps(self.body).encode()

def test_pages_accept_real_next_shape(monkeypatch):
    urls = [f"{BASE}?_getpages=abc&_getpagesoffset={n}&_count=100" for n in (100, 200)]
    bundles = [
        {"entry": [{"resource": {"id": "1"}}], "link": [{"relation": "next", "url": urls[0]}]},
        {"entry": [{"resource": {"id": "2"}}], "link": [{"relation": "next", "url": urls[1]}]},
        {"entry": [{"resource": {"id": "3"}}]},
    ]
    monkeypatch.setattr(sandbox_client.httpx, "get", lambda *args, **kwargs: Response(bundles.pop(0)))
    assert [page[0]["id"] for page in sandbox_client.SandboxClient(BASE).pages("Observation")] == ["1", "2", "3"]

@pytest.mark.parametrize("url", ["http://sandbox.hl7europe.eu/oneaquahealth/fhir", "https://evil.test/x", f"{BASE}EVIL/x"])
def test_pages_reject_bad_next_origin(monkeypatch, url):
    body = {"link": [{"relation": "next", "url": url}]}
    monkeypatch.setattr(sandbox_client.httpx, "get", lambda *args, **kwargs: Response(body))
    with pytest.raises(RuntimeError):
        list(sandbox_client.SandboxClient(BASE).pages("Observation"))

def test_retry_and_resource_type(monkeypatch):
    calls = []
    def get(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ConnectError("x")
        return Response({})
    monkeypatch.setattr(sandbox_client.httpx, "get", get)
    monkeypatch.setattr(sandbox_client.time, "sleep", lambda _: None)
    assert list(sandbox_client.SandboxClient(BASE, retries=2).pages("Observation")) == [[]]
    assert len(calls) == 3
    for value in ("Observación", "../x", "Obs1", ""):
        with pytest.raises(ValueError):
            list(sandbox_client.SandboxClient(BASE).pages(value))

def test_circuit_breaker_cooldown(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(sandbox_client.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(sandbox_client.time, "sleep", lambda _: None)
    monkeypatch.setattr(sandbox_client.httpx, "get", lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ConnectError("x")))
    client = sandbox_client.SandboxClient(BASE, retries=0, failure_limit=1, cooldown_seconds=5)
    with pytest.raises(httpx.ConnectError):
        client._request(BASE)
    with pytest.raises(RuntimeError, match="circuit breaker is open"):
        client._request(BASE)
    clock[0] = 6.0
    monkeypatch.setattr(sandbox_client.httpx, "get", lambda *args, **kwargs: Response({}))
    assert client._request(BASE) == {}

def test_snapshot_metadata(monkeypatch, tmp_path):
    target = tmp_path / "Observation.json"
    monkeypatch.setattr(sandbox_client, "sandbox_snapshot_path", lambda _: target)
    monkeypatch.setattr(sandbox_client.SandboxClient, "pages", lambda *args: iter([[{"id": "a"}]]))
    sandbox_client.SandboxClient(BASE).snapshot("Observation")
    metadata = json.loads(target.with_suffix(".metadata.json").read_text())
    assert metadata["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert metadata["count"] == 1 and metadata["origin"] == "real-sandbox"
    assert not list(tmp_path.glob("*.tmp"))


def test_get_resource_rejects_ids_outside_the_fhir_id_charset():
    client = sandbox_client.SandboxClient(BASE)
    for bad_id in ("../../etc/passwd", "Obs/1", "Obs 1", "Obs\n1", "Obs;drop"):
        with pytest.raises(ValueError, match="outside the FHIR id charset"):
            client.get_resource("Observation", bad_id)


def test_get_resource_accepts_a_valid_fhir_id(monkeypatch):
    client = sandbox_client.SandboxClient(BASE)
    captured = {}

    def fake_request(self, url, params=None):
        captured["url"] = url
        return {"resourceType": "Observation", "id": "Obs-Almyros-Ph-2018"}

    monkeypatch.setattr(sandbox_client.SandboxClient, "_request", fake_request)
    result = client.get_resource("Observation", "Obs-Almyros-Ph-2018")
    assert result["id"] == "Obs-Almyros-Ph-2018"
    assert captured["url"] == f"{BASE}/Observation/Obs-Almyros-Ph-2018"
