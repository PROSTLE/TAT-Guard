"""Regression tests for nonhalluc/claim_scan.py (run from repo root: pytest tests/)."""
import pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def scan(tmp_path, text):
    f = tmp_path / "doc.md"
    f.write_text(text, encoding="utf-8")
    return subprocess.run([sys.executable, str(ROOT / "nonhalluc" / "claim_scan.py"), str(f)],
                          cwd=ROOT, capture_output=True, text=True, encoding="utf-8")


def test_tagged_number_passes(tmp_path):
    assert scan(tmp_path, "UPI did 24.07 bn txns [UPI-SEP26].\n").returncode == 0


def test_untagged_rupee_flagged(tmp_path):
    r = scan(tmp_path, "Banks lose ₹4.0 lakh a day.\n")
    assert r.returncode == 1 and "UNSOURCED" in r.stdout


def test_percent_followed_by_space_flagged(tmp_path):
    # the original 04 §4 regex missed this case
    r = scan(tmp_path, "Complaints rose 13.55% from last year.\n")
    assert r.returncode == 1 and "13.55%" in r.stdout


def test_unknown_tag_flagged(tmp_path):
    r = scan(tmp_path, "Volume 24.07 bn [NOPE-X].\n")
    assert r.returncode == 1 and "unknown tags" in r.stdout
