"""Same reconciliation, two engines: the pandas matcher vs the Exasol recon last logged in reports/timings.csv.

    python crosscheck/benchmark.py --data data/1m

Run right after `recon/pipeline.py recon`, with nothing else heavy running. Both sides produce the same exceptions
(crosscheck/dual_impl.py proves that). The pandas time includes reading the CSVs, because pandas keeps nothing between
runs; Exasol's load time is reported beside its recon time so the comparison can be read either way. One machine, one
run each: the report states what was measured and nothing more.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
from crosscheck.dual_impl import classify  # noqa: E402


def exasol_timings(rows: int) -> tuple[float, float]:
    """(recon s, load s): the latest full recon and the latest load of this many rows, from reports/timings.csv."""
    with open(ROOT / "reports" / "timings.csv", newline="", encoding="utf-8") as fh:
        log = [r for r in csv.DictReader(fh)]
    recon_runs = [r["run_id"] for r in log if r["step"] == "recon 30_penalty_view.sql" and r["scale"] != "after-action"]
    if not recon_runs:
        raise SystemExit("no recon run in reports/timings.csv")
    recon = sum(int(r["duration_ms"]) for r in log if r["run_id"] == recon_runs[-1] and r["step"].startswith("recon "))
    loads = [r for r in log if r["scale"] == str(rows) and r["step"].startswith("load ")]
    last = loads[-1]["run_id"] if loads else None
    load = sum(int(r["duration_ms"]) for r in loads if r["run_id"] == last)
    return recon / 1000, load / 1000


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", required=True)
    a = ap.parse_args()
    data = pathlib.Path(a.data)
    rows = json.loads((data / "manifest.json").read_text(encoding="utf-8"))["rows"]
    t0 = time.perf_counter()
    pred = classify(data)
    pandas_s = time.perf_counter() - t0
    recon_s, load_s = exasol_timings(rows)
    body = ["# Benchmark: Exasol vs pandas, same reconciliation\n",
            f"Date: {dt.datetime.now().astimezone().isoformat(timespec='seconds')}. Data: {a.data} ({rows} transactions, SYNTHETIC). "
            f"One laptop, one run of each, Exasol in Podman on WSL2 with 2 GiB of memory.\n",
            "| Engine | Step | Seconds |", "|---|---|---|",
            f"| pandas | read CSVs + match + classify, {len(pred)} exceptions | {pandas_s:.1f} |",
            f"| Exasol | full recon, data already in the database | {recon_s:.1f} |",
            f"| Exasol | bulk load of the same CSVs (latest load at this scale) | {load_s:.1f} |",
            "\nCaveat: laptop timings, not a server benchmark. Exasol is limited to its VM's memory and pandas is not."]
    rep = ROOT / "reports" / f"benchmark_{rows}_{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}.md"
    rep.write_text("\n".join(body), encoding="utf-8")
    print(rep)
    print("\n".join(body))


if __name__ == "__main__":
    main()
