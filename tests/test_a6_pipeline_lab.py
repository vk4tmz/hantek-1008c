from pathlib import Path
import py_compile


def test_a6_pipeline_lab_compiles():
    path = Path(__file__).resolve().parents[1] / "tools" / "lab_a6_pipeline.py"
    py_compile.compile(str(path), doraise=True)
