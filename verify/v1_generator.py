"""V1 gate (03_VERIFIER.md): generator checks that do not need the database.

    python verify/v1_generator.py            # writes reports/verifier_V1_<ts>.md

Checks: determinism (two runs, same seed -> identical SHA-256 per file), row counts vs manifest,
ground-truth coverage (every injected break type >= 100 at 1M rows), money columns are integers >= 0,
no real PII (masked accounts, synthetic ids only). The "Load" check lives in verify/v1_load.py.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
GEN = [sys.executable, str(ROOT / "generator" / "generate.py")]
BREAKS = ["DEBIT_NO_CREDIT", "NPCI_SUCCESS_NO_CBS", "AMOUNT_MISMATCH", "DUPLICATE_POSTING", "LATE_FILE",
          "NARRATION_ONLY"]                       # the six types listed in 01_BUILD_PLAN.md Phase 1
MONEY = {"switch_log": ["AMOUNT_PAISE"], "npci_settlement": ["AMOUNT_PAISE"],
         "npci_settlement_pending": ["AMOUNT_PAISE"], "cbs_ledger": ["AMOUNT_PAISE"],
         "ground_truth": ["AMOUNT_PAISE", "COMP_PAID_PAISE"]}
ACCT = re.compile(r"^X{8}\d{4}$")


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def run(rows, seed, out):
    t = time.perf_counter()
    r = subprocess.run(GEN + ["--rows", str(rows), "--seed", str(seed), "--out", str(out)],
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stderr)
    return time.perf_counter() - t


def count_rows(p):
    with open(p, encoding="utf-8", newline="") as fh:
        return sum(1 for _ in fh) - 1


def main():
    results, log = [], []
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="tatguard_v1_"))

    # 1. determinism
    secs = [run(100_000, 42, tmp / f"gen_{k}") for k in ("a", "b")]
    det = []
    for f in sorted((tmp / "gen_a").iterdir()):
        a, b = sha(f), sha(tmp / "gen_b" / f.name)
        det.append(f"{'PASS' if a == b else 'FAIL'} {f.name} {a[:16]}")
    other = run(100_000, 43, tmp / "gen_c")
    differs = sha(tmp / "gen_a" / "switch_log.csv") != sha(tmp / "gen_c" / "switch_log.csv")
    log += ["## Determinism (rows=100000, seed=42, two runs)", *det,
            f"seed 43 switch_log differs from seed 42: {differs}", f"run seconds: {secs + [other]}"]
    results.append(("Determinism", all(d.startswith("PASS") for d in det) and differs,
                    f"{len(det)} files identical across runs; a different seed changes output"))

    # 2-5 on a 1M run
    big = tmp / "gen_1m"
    t1m = run(1_000_000, 42, big)
    man = json.loads((big / "manifest.json").read_text(encoding="utf-8"))
    rc_ok, rc_lines = True, []
    for name, n in man["row_counts"].items():
        actual = count_rows(big / f"{name}.csv")
        rc_ok &= actual == n
        rc_lines.append(f"{name}: manifest={n} file={actual}")
    sw = man["row_counts"]["switch_log"]
    rc_ok &= sw == 1_000_000
    log += ["## Row counts (rows=1000000)", *rc_lines, f"generation seconds: {t1m:.1f}"]
    results.append(("Row counts", rc_ok, f"switch_log={sw} (= requested); all files match manifest"))

    with open(big / "ground_truth.csv", encoding="utf-8", newline="") as fh:
        labels = Counter(r["INJECTED_BREAK"] for r in csv.DictReader(fh))
    cov = {b: labels.get(b, 0) for b in BREAKS}
    log += ["## Ground-truth coverage (1M)", *[f"{k}: {v}" for k, v in sorted(labels.items())]]
    results.append(("Ground truth coverage", all(v >= 100 for v in cov.values()),
                    "min over the six break types = " + str(min(cov.values()))))

    money_ok, bad = True, []
    for name, cols in MONEY.items():
        with open(big / f"{name}.csv", encoding="utf-8", newline="") as fh:
            for i, r in enumerate(csv.DictReader(fh)):
                for c in cols:
                    v = r[c]
                    if v == "" and c == "COMP_PAID_PAISE":
                        continue
                    if not v.isdigit():
                        money_ok = False
                        bad.append(f"{name}:{i}:{c}={v!r}")
                        break
    log += ["## Money columns", f"non-integer or negative values: {bad[:10]}"]
    results.append(("Money type", money_ok, "every AMOUNT_PAISE / COMP_PAID_PAISE is a non-negative integer string"))

    pii_ok, pii_bad = True, []
    with open(big / "cbs_ledger.csv", encoding="utf-8", newline="") as fh:
        for i, r in enumerate(csv.DictReader(fh)):
            if not ACCT.match(r["ACCOUNT_NO_MASKED"]):
                pii_ok = False
                pii_bad.append(r["ACCOUNT_NO_MASKED"])
                if len(pii_bad) > 5:
                    break
    log += ["## PII", f"unmasked accounts: {pii_bad}",
            "names: generator emits no personal names (payees are synthetic P#######/MERCH###### tokens)"]
    results.append(("No real PII", pii_ok and man.get("synthetic") is True,
                    "all accounts match XXXXXXXX#### ; manifest synthetic=true"))
    results.append(("Load (COUNT(*) in Exasol)", None, "see verify/v1_load.py"))

    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    commit = r.stdout.strip() if r.returncode == 0 else "none (no commits)"   # with no commits git prints "HEAD"
    ts = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    rep = ROOT / "reports" / f"verifier_V1_{ts}.md"
    verdict = lambda v: "PASS" if v is True else ("FAIL" if v is False else "SEE NOTE")
    fails = sum(1 for _, v, _ in results if v is False)
    body = [f"# Verifier report: V1 (Generator)\n", "```",
            f"PHASE: V1   COMMIT: {commit}   DATE: {dt.datetime.now().astimezone().isoformat(timespec='seconds')}", "```",
            "| Check | Verdict | Evidence |", "|---|---|---|",
            *[f"| {n} | {verdict(v)} | {e} |" for n, v, e in results],
            f"\n**Generator-side: {'PASS' if not fails else f'FAIL ({fails} failing)'}**\n", "## Raw output", "```", *log, "```"]
    rep.write_text("\n".join(body), encoding="utf-8")
    print(rep)
    print("\n".join(body[4:4 + len(results) + 2]))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
