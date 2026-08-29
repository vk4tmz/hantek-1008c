from tools import probe_official_scan


def test_next_four_selects_only_pre_collision_scan_profiles():
    select_profiles = getattr(probe_official_scan, "select_profiles", None)
    assert select_profiles is not None, "batch profile selector is missing"
    assert select_profiles("next-four") == ("1e", "1f", "20", "21")
