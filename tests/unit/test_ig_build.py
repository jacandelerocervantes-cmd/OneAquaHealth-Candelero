from oah.fhir.ig_build import find_sushi, resource_counts, sushi_totals

def test_counts_use_resource_type_not_profile_text():
    resources = [{"resourceType": "StructureDefinition"}, {"resourceType": "ValueSet"}, {"resourceType": "CodeSystem"}, {"resourceType": "Observation", "meta": {"profile": ["StructureDefinition"]}}]
    assert resource_counts(resources) == {"StructureDefinition": 1, "ValueSet": 1, "CodeSystem": 1}

def test_sushi_totals_parser():
    assert sushi_totals("0 Errors      0 Warnings") == (0, 0)
    assert sushi_totals("2 Errors 3 Warnings") == (2, 3)
    assert sushi_totals("no summary") is None

def test_find_sushi_windows(monkeypatch):
    monkeypatch.setattr("oah.fhir.ig_build.os.name", "nt")
    monkeypatch.setattr("oah.fhir.ig_build.shutil.which", lambda name: "cmd" if name == "sushi.cmd" else None)
    assert find_sushi() == "cmd"
