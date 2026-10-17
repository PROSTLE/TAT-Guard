"""V1 gate, "Load" check (03_VERIFIER.md): SELECT COUNT(*) in Exasol = file row count for every table.

    python recon/pipeline.py load --data data/1m
    python verify/v1_load.py --data data/1m       # writes reports/verifier_V1load_<ts>.md

Also loads ground_truth.csv into VERIFIER.GROUND_TRUTH. That table is verifier-only (03 V2), so it is loaded
here, not by recon/pipeline.py. Credentials come only from env vars EXA_DSN, EXA_USER, EXA_PASSWORD.
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
from recon.pipeline import IMPORT_PARAMS, connect  # noqa: E402

TABLES = {  # manifest row_counts key -> table
    "switch_log": ("RAW", "SWITCH_LOG"),
    "npci_settlement": ("RAW", "NPCI_SETTLEMENT"),
    "cbs_ledger": ("RAW", "CBS_LEDGER"),
    "settlement_file_log": ("RAW", "SETTLEMENT_FILE_LOG"),
    "ground_truth": ("VERIFIER", "GROUND_TRUTH"),
}


def main(argv=None):
    ap = argparse.ArgumentParser(description="V1 load check")
    ap.add_argument("--data", required=True)
    a = ap.parse_args(argv)
    data = pathlib.Path(a.data)
    man = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    rc = man["row_counts"]
    C = connect()
    try:
        C.execute('TRUNCATE TABLE "VERIFIER"."GROUND_TRUTH"')
        C.import_from_file(str(data / "ground_truth.csv"), ("VERIFIER", "GROUND_TRUTH"), IMPORT_PARAMS)
        results = []
        for key, (schema, name) in TABLES.items():
            got = C.execute(f'SELECT COUNT(*) FROM "{schema}"."{name}"').fetchval()
            want = rc[key]
            ok, note = got == want, ""
            # after `pipeline.py ingest-pending` the late file's rows are in RAW.NPCI_SETTLEMENT too
            if key == "npci_settlement" and not ok and got == want + rc["npci_settlement_pending"]:
                ok, note = True, " (includes the ingested pending file)"
            results.append((f"{schema}.{name}", ok, f"COUNT(*)={got} manifest={want}{note}"))
    finally:
        C.close()

    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    commit = r.stdout.strip() if r.returncode == 0 else "none (no commits)"
    fails = sum(1 for _, ok, _ in results if not ok)
    body = ["# Verifier report: V1 Load\n", "```",
            f"PHASE: V1-load   COMMIT: {commit}   DATE: {dt.datetime.now().astimezone().isoformat(timespec='seconds')}",
            f"DATA: {data}   seed={man['seed']} rows={man['rows']}", "```",
            "| Table | Verdict | Evidence |", "|---|---|---|",
            *[f"| {t} | {'PASS' if ok else 'FAIL'} | {e} |" for t, ok, e in results],
            f"\n**OVERALL: {'PASS' if not fails else f'FAIL ({fails} failing)'}**"]
    rep = ROOT / "reports" / f"verifier_V1load_{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}.md"
    rep.write_text("\n".join(body), encoding="utf-8")
    print(rep)
    print("\n".join(body[5:]))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
