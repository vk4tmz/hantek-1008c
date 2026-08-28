from pathlib import Path
import ast


def test_overlap_lab_is_diagnostic_and_has_expected_modes():
    path = Path(__file__).resolve().parents[1] / "tools" / "lab_overlap_transfer.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")
    assert "unread-rearm" in text
    assert "partial-rearm" in text
    assert "Canonical acquisition is not modified" in text
    assert any(isinstance(node, ast.FunctionDef) and node.name == "run_one" for node in ast.walk(tree))
