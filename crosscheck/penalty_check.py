"""Penalty SQL view vs Python reference, to the rupee (02_CROSS_CHECK.md §4, 03_VERIFIER.md V3).

    python crosscheck/penalty_check.py [--limit 10000]

Reads a deterministic sample of RECON.PENALTY_EXPOSURE (ordered by HASH_MD5 of EXC_ID) and recomputes
deadline, penalty and next-24h exposure with recon/penalty.py. Exit code 1 on any difference.
Credentials come only from env vars EXA_DSN, EXA_USER, EXA_PASSWORD.
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from recon.penalty import deadline, exposure_next_24h, penalty_rupees  # noqa: E402
from recon.pipeline import connect  # noqa: E402

COLS = ["EXC_ID", "CASE_NAME", "STATUS", "TXN_DT", "END_DT", "AS_OF_DT", "DEADLINE_DT",
        "PENALTY_PAISE", "EXPOSURE_NEXT_24H_PAISE"]


def d(v) -> dt.date:
    return dt.date.fromisoformat(str(v)[:10])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, default=10000)
    a = ap.parse_args(argv)
    C = connect()
    try:
        rows = C.execute(f'SELECT {", ".join(chr(34) + c + chr(34) for c in COLS)} FROM "RECON"."PENALTY_EXPOSURE" '
                         'ORDER BY HASH_MD5("EXC_ID") LIMIT {n!d}', {"n": a.limit}).fetchall()
    finally:
        C.close()
    diffs = []
    for r in rows:
        x = dict(zip(COLS, r))
        case, t = x["CASE_NAME"], d(x["TXN_DT"])
        want = {
            "DEADLINE_DT": deadline(t, case),
            "PENALTY_PAISE": penalty_rupees(t, d(x["END_DT"]), case) * 100,
            # open cases accrue tomorrow; reversed cases are frozen at R
            "EXPOSURE_NEXT_24H_PAISE": (exposure_next_24h(t, d(x["AS_OF_DT"]), case) if x["STATUS"] == "OPEN"
                                        else penalty_rupees(t, d(x["END_DT"]), case)) * 100,
        }
        got = {"DEADLINE_DT": d(x["DEADLINE_DT"]), "PENALTY_PAISE": int(x["PENALTY_PAISE"]),
               "EXPOSURE_NEXT_24H_PAISE": int(x["EXPOSURE_NEXT_24H_PAISE"])}
        diffs += [(x["EXC_ID"], k, got[k], want[k]) for k in want if got[k] != want[k]]
    print(f"rows compared: {len(rows)}   differences: {len(diffs)}")
    for e in diffs[:20]:
        print("  EXC_ID={} {}: sql={} python={}".format(*e))
    if not rows:
        print("BLOCKED: PENALTY_EXPOSURE returned no rows (run recon first)")
    sys.exit(1 if diffs or not rows else 0)


if __name__ == "__main__":
    main()
