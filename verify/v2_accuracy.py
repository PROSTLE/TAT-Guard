"""V2 gate (03_VERIFIER.md): matching accuracy of RECON.EXCEPTIONS vs VERIFIER.GROUND_TRUTH, per class.

    python verify/v2_accuracy.py --data data/1m      # run right after `recon` (before approvals / ingest-pending)

Uses the per-class confusion query from 03 V2 (ground truth now lives in schema VERIFIER). Precision and recall are
computed in Python from the query result. Targets (ours, 03 V2): recall >= 0.99 for DEBIT_NO_CREDIT, overall
precision >= 0.98. Real numbers are reported whatever they are.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
from recon.pipeline import connect, host_label  # noqa: E402

CONFUSION_SQL = """WITH gt AS (SELECT "UPI_TXN_ID", "EXPECTED_CLASS" FROM "VERIFIER"."GROUND_TRUTH"),
     pr AS (SELECT "UPI_TXN_ID", "CLASS" FROM "RECON"."EXCEPTIONS")
SELECT COALESCE(gt."EXPECTED_CLASS", pr."CLASS") AS "CLS",
       SUM(CASE WHEN gt."EXPECTED_CLASS" = pr."CLASS" THEN 1 ELSE 0 END) AS "TP",
       SUM(CASE WHEN pr."CLASS" IS NOT NULL AND (gt."EXPECTED_CLASS" IS NULL OR gt."EXPECTED_CLASS" <> pr."CLASS") THEN 1 ELSE 0 END) AS "FP",
       SUM(CASE WHEN gt."EXPECTED_CLASS" IS NOT NULL AND (pr."CLASS" IS NULL OR gt."EXPECTED_CLASS" <> pr."CLASS") THEN 1 ELSE 0 END) AS "FN"
FROM gt FULL OUTER JOIN pr ON gt."UPI_TXN_ID" = pr."UPI_TXN_ID"
GROUP BY COALESCE(gt."EXPECTED_CLASS", pr."CLASS") ORDER BY 1"""


def ratio(a, b):
    return None if b == 0 else a / b


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    a = ap.parse_args(argv)
    man = json.loads((pathlib.Path(a.data) / "manifest.json").read_text(encoding="utf-8"))
    C = connect()
    try:
        n_rows = C.execute('SELECT COUNT(*) FROM "RAW"."SWITCH_LOG"').fetchval()
        rows = C.execute(CONFUSION_SQL).fetchall()
        orphan = C.execute("""SELECT COUNT(*) FROM "RECON"."EXCEPTIONS" WHERE "UPI_TXN_ID" IS NULL""").fetchval()
    finally:
        C.close()
    if n_rows != man["row_counts"]["switch_log"]:
        raise SystemExit(f"DB holds {n_rows} switch rows but {a.data} has {man['row_counts']['switch_log']}: wrong dataset loaded")
    table, tp_all, fp_all = [], 0, 0
    for cls, tp, fp, fn in rows:
        tp, fp, fn = int(tp), int(fp), int(fn)
        if cls is None:          # ground-truth rows with no expected class and no exception: correct negatives
            continue
        tp_all, fp_all = tp_all + tp, fp_all + fp
        table.append((cls, tp, fp, fn, ratio(tp, tp + fp), ratio(tp, tp + fn)))
    dnc = next((t for t in table if t[0] == "DEBIT_NO_CREDIT"), None)
    overall_p = ratio(tp_all, tp_all + fp_all)
    checks = [("DEBIT_NO_CREDIT recall >= 0.99 (our target)", dnc is not None and dnc[5] is not None and dnc[5] >= 0.99),
              ("overall precision >= 0.98 (our target)", overall_p is not None and overall_p >= 0.98)]
    fmt = lambda v: "n/a" if v is None else f"{v:.4f}"
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    commit = r.stdout.strip() if r.returncode == 0 else "none (no commits)"
    body = ["# Verifier report: V2 (Matching accuracy)\n", "```",
            f"PHASE: V2   COMMIT: {commit}   DATE: {dt.datetime.now().astimezone().isoformat(timespec='seconds')}",
            f"DATA: {a.data} (rows={man['rows']}, seed={man['seed']})   HOST: {host_label()}", "```",
            "| Class | TP | FP | FN | Precision | Recall |", "|---|---|---|---|---|---|",
            *[f"| {c} | {tp} | {fp} | {fn} | {fmt(p)} | {fmt(rc)} |" for c, tp, fp, fn, p, rc in table],
            f"\nOverall precision: {tp_all:,} / {tp_all + fp_all:,} = {overall_p:.6f}. Exceptions with no UPI_TXN_ID "
            f"(UNMATCHED_CBS_DEBIT, sent to a human): {orphan}.", "",
            "| Check | Verdict |", "|---|---|", *[f"| {n} | {'PASS' if ok else 'FAIL'} |" for n, ok in checks],
            f"\n**OVERALL: {'PASS' if all(ok for _, ok in checks) else 'FAIL'}**",
            "\nCaveat: SYNTHETIC data. The score shows the engine finds the breaks this generator injects, not real-world accuracy."]
    rep = ROOT / "reports" / f"verifier_V2_{man['rows']}_{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}.md"
    rep.write_text("\n".join(body), encoding="utf-8")
    print(rep)
    print("\n".join(body[5:]))
    sys.exit(0 if all(ok for _, ok in checks) else 1)


if __name__ == "__main__":
    main()
