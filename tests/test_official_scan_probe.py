import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "probe_official_scan.py"

spec = importlib.util.spec_from_file_location("probe_official_scan", SCRIPT)
assert spec is not None
assert spec.loader is not None

probe_official_scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe_official_scan)


def test_next_four_selects_only_pre_collision_scan_profiles():
    select_profiles = getattr(probe_official_scan, "select_profiles", None)
    assert select_profiles is not None, "batch profile selector is missing"
    assert select_profiles("next-four") == ("1e", "1f", "20", "21")
