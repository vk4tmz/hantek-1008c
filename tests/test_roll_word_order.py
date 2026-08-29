from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_TOOL = Path(__file__).resolve().parents[1] / "tools" / "analyze_roll_word_order.py"
_spec = spec_from_file_location("analyze_roll_word_order", _TOOL)
_mod = module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)


def pack_rows(rows):
    out = bytearray()
    for w0, w1 in rows:
        out += int(w0).to_bytes(2, "little")
        out += int(w1).to_bytes(2, "little")
    return bytes(out)


def test_uniform_interleaved_sequence_has_equal_alternating_deltas():
    raw = pack_rows([(100, 101), (102, 103), (104, 105), (106, 107)])
    report = _mod.analyze(raw)
    assert report["within_word0_to_word1"]["mean_abs_delta"] == 1
    assert report["across_word1_to_next_word0"]["mean_abs_delta"] == 1
    assert report["word0_to_next_word0"]["mean_abs_delta"] == 2
    assert report["word1_to_next_word1"]["mean_abs_delta"] == 2
    assert report["across_to_within_mean_abs_delta_ratio"] == 1


def test_roll_words_are_masked_to_12_bits():
    raw = pack_rows([(0xF123, 0xE124), (0xD125, 0xC126)])
    assert _mod.rows_from_raw(raw) == [(0x123, 0x124), (0x125, 0x126)]
