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


def test_channel_count_parser_supports_descending_matrix():
    assert probe_official_scan.parse_channel_counts("all-desc") == (8, 7, 6, 5, 4, 3, 2, 1)
    assert probe_official_scan.parse_channel_counts("8,4,1") == (8, 4, 1)


def test_channel_set_parser_supports_sparse_batch():
    assert probe_official_scan.parse_channel_sets("1,8;2,5;1,2,5,8") == (
        (1, 8), (2, 5), (1, 2, 5, 8)
    )


def test_multichannel_candidate_views_preserve_both_layout_hypotheses():
    words = list(range(16))
    views = probe_official_scan.multichannel_candidate_views(words, 3)
    assert views["physical_width_candidate"] == 4
    assert views["dummy_lane_candidate"] == 4
    assert views["word_interleaved"]["complete_rows"] == 4
    assert views["word_interleaved"]["lanes"][0]["samples"] == 4
    assert views["paired_observations_per_channel"]["complete_rows"] == 2
    assert views["paired_observations_per_channel"]["lanes"][0]["samples"] == 4
