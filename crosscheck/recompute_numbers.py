"""Recompute every derived number used in README/deck/video from facts.yaml (02_CROSS_CHECK.md §3).

    python crosscheck/recompute_numbers.py   # prints PASS/FAIL per number; exit 1 on any FAIL

Named recompute_numbers.py, not numbers.py as in 02 §3: a file called numbers.py in crosscheck/ shadows the
standard-library module `numbers` for every script in this folder (decimal, numpy and pandas import it).

The impact estimate (01_BUILD_PLAN.md Appendix B) mixes one FACT with two ASSUMPTIONs. Wherever it is shown
it must be labelled [ASSUMPTION]; the assumption values live only here.
"""
from __future__ import annotations

import math
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")
facts = {f["id"]: f for f in yaml.safe_load(open(ROOT / "facts.yaml", encoding="utf-8"))["facts"]}

ASSUME_DNC_RATE = 0.0001   # ASSUMPTION: share of UPI txns that end debited-not-credited (not a fact)
ASSUME_MISS_RATE = 0.05    # ASSUMPTION: share of those that miss TAT by one day (not a fact)


def check(label, computed, stated, tol=0.01):
    ok = math.isclose(computed, stated, rel_tol=tol)
    print(f"{'PASS' if ok else 'FAIL'} | {label} | computed={computed:,.2f} stated={stated:,.2f}")
    return ok


results = []
daily = facts["UPI-SEP26"]["value"]["daily_avg_txns"]
rs_per_day = facts["RBI-TAT-COMP"]["value"]
per_day = daily * ASSUME_DNC_RATE * ASSUME_MISS_RATE * rs_per_day
results.append(check("impact estimate Rs/day [ASSUMPTION]", per_day, 401_000))
results.append(check("impact estimate Rs crore/yr [ASSUMPTION]", per_day * 365 / 1e7, 14.64))
results.append(check("Sept 2026 volume (bn) vs daily avg x 30 [UPI-SEP26]", daily * 30 / 1e9,
                     facts["UPI-SEP26"]["value"]["monthly_txns_bn"], tol=0.02))
print(f"\n{sum(results)}/{len(results)} PASS")
sys.exit(0 if all(results) else 1)
