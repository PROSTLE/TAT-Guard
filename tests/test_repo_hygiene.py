"""Repo-level guards."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CODE_DIRS = ["agent", "crosscheck", "generator", "nonhalluc", "recon", "tests", "ui", "verify", "import"]


def test_no_module_shadows_the_standard_library():
    # crosscheck/numbers.py once shadowed stdlib `numbers`, so other scripts in crosscheck/ silently ran it instead
    clashes = [str(p.relative_to(ROOT)) for d in CODE_DIRS for p in (ROOT / d).glob("*.py")
               if p.stem in sys.stdlib_module_names]
    assert not clashes, clashes
