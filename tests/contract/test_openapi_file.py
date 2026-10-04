"""The committed OpenAPI file (docs/openapi.json) is the schema the running app serves."""
import json

from oah.api.app import app
from oah.paths import openapi_path


def test_the_committed_openapi_file_matches_the_app():
    committed = json.loads(openapi_path().read_text(encoding="utf-8"))
    assert committed == json.loads(json.dumps(app.openapi())), "run: python scripts/export_openapi.py"


def test_the_committed_file_lists_the_new_routes():
    paths = json.loads(openapi_path().read_text(encoding="utf-8"))["paths"]
    assert "/countries" in paths and "/sites/{location_id}/measurements" in paths
