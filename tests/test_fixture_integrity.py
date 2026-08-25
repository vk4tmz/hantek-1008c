
def test_uploaded_fixture_sha256_manifest():
    import json, hashlib
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/"tests"/"fixtures"/"SHA256SUMS.json").read_text())
    for rel,want in manifest.items():
        got=hashlib.sha256((root/rel).read_bytes()).hexdigest()
        assert got == want, rel
