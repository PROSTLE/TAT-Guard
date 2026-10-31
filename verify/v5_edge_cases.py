"""V5 gate: edge cases the generator never injects, run through the real SQL on real Exasol.

    python verify/v5_edge_cases.py

V2 proves the engine finds the breaks the generator injects. It cannot prove anything about a case the generator never
makes, such as a partial reversal. This script runs sql/10_*, 15_ and 30_ unchanged, except that schema names are
rewritten to throwaway TGE_* schemas, over a few handcrafted rows, checks each expectation, and drops the schemas.
RAW, RECON, AUDIT and VERIFIER are never touched. Rows are SYNTHETIC. Settings come from recon/config.yaml and facts.yaml.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import re
import subprocess
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
from recon import pipeline, rules  # noqa: E402
from ui.server import load_dotenv  # noqa: E402

SCHEMAS = ("RAW", "RECON", "AUDIT", "VERIFIER")
AS_OF = dt.datetime(2026, 10, 8, 6, 0, 0)     # DESIGN: fixed cut-off of this handcrafted case set
TAT = rules.tat_days()
RATE = rules.paise_per_day()
P2P_TAT = TAT[rules.case_for("P2P", "UPI")]


def scoped(sql: str) -> str:
    """Rewrite schema names only. The word boundaries keep RECON inside a longer identifier untouched."""
    return re.sub(r'(?<![A-Za-z0-9_])"?(' + "|".join(SCHEMAS) + r')"?(?=\s*\.|\s*;)', lambda m: f'"TGE_{m.group(1)}"', sql)


def run_sql_file(C, name: str):
    C.execute_sql_script(scoped((ROOT / "sql" / name).read_text(encoding="utf-8")))


def txn(n, day, status, debits=(), reversals=(), comp=0, typ="P2P", amount=100000):
    """One transaction: NPCI status, CBS debits and reversals as (amount_paise, day)."""
    rrn, uid = f"{n:012d}", f"TGE{n:09d}"
    ts = dt.datetime(2026, 10, day, 10, 0, 0)
    sw = (uid, rrn, ts, amount, "FAILED" if status == "FAILED" else "SUCCESS", "TD01" if status == "FAILED" else "00", "APP")
    npci = (uid, rrn, ts, ts.date(), 1, amount, "BANK1", "BANK2", typ, "TD01" if status == "FAILED" else "00", status)
    cbs = [(f"D{n}{i}", "XXXX0001", ts + dt.timedelta(seconds=5), "DR", a, f"UPI/DR/{rrn}/X") for i, a in enumerate(debits)]
    cbs += [(f"R{n}{i}", "XXXX0001", dt.datetime(2026, 10, d, 12, 0, 0), "CR", a, f"UPI/REV/{rrn}/X") for i, (a, d) in enumerate(reversals)]
    if comp:
        cbs.append((f"C{n}", "XXXX0001", AS_OF, "CR", comp, f"TAT COMP/{rrn}/{comp // 100}"))
    return uid, sw, npci, cbs


CASES = {
    "partial":  txn(1, 7, "FAILED", [100000], [(40000, 7)]),                 # 40% reversed: still open, clock running
    "instalments": txn(2, 1, "FAILED", [100000], [(60000, 1), (40000, 2)]),  # fully reversed; R is the LAST reversal
    "double_debit_failed": txn(3, 2, "FAILED", [100000, 100000]),            # must keep its TAT clock
    "full": txn(4, 7, "FAILED", [100000], [(100000, 7)]),                    # ordinary full reversal
    "overdue_old": txn(5, 1, "FAILED", [100000]),                            # accruing, waited longest
    "overdue_new_big": txn(6, 3, "FAILED", [900000], amount=900000),         # accruing, larger amount, waited less
    "at_risk": txn(7, 7, "FAILED", [100000]),                                # deadline is the cut-off date
    "comp_due": txn(8, 1, "FAILED", [100000], [(100000, 5)]),                # reversed late, nothing paid, adds nothing tomorrow
    "within_tat": txn(9, 7, "FAILED", [100000], typ="P2M"),                  # still inside T+5
    "duplicate_ok": txn(10, 7, "SUCCESS", [100000, 100000]),                 # success + two debits: still a duplicate
}


def load(C):
    for s in SCHEMAS:
        C.execute(f'DROP SCHEMA IF EXISTS "TGE_{s}" CASCADE')
    C.execute_sql_script(scoped((ROOT / "sql" / "00_schemas.sql").read_text(encoding="utf-8")))
    C.execute('CREATE TABLE IF NOT EXISTS "TGE_RECON"."RUN_LOG" (X DECIMAL(1,0))')
    tuples = list(CASES.values())
    C.import_from_iterable([t[1] for t in tuples], ("TGE_RAW", "SWITCH_LOG"))
    C.import_from_iterable([t[2] for t in tuples], ("TGE_RAW", "NPCI_SETTLEMENT"))
    C.import_from_iterable([row for t in tuples for row in t[3]], ("TGE_RAW", "CBS_LEDGER"))
    C.import_from_iterable([(dt.date(2026, 10, 1), 1, dt.datetime(2026, 10, 1), dt.datetime(2026, 10, 9),
                             dt.datetime(2026, 10, 1, 12), dt.datetime(2026, 10, 1, 12), len(tuples))],
                           ("TGE_RAW", "SETTLEMENT_FILE_LOG"))
    cfg = yaml.safe_load(open(ROOT / "recon" / "config.yaml", encoding="utf-8"))
    m = cfg["matching"]
    settings = {"as_of": AS_OF.strftime("%Y-%m-%d %H:%M:%S"), "pass2_window_s": m["pass2_window_s"],
                "pass4_window_s": m["pass4_window_s"], "pass4_threshold": m["pass4_threshold"],
                "ref_pattern": m["ref_pattern"], "rail": cfg["rail"],
                **{f"pass4_w_{k}": v for k, v in m["pass4_weights"].items()}}
    C.import_from_iterable([(k, str(v)) for k, v in settings.items()], ("TGE_RECON", "SETTINGS"))
    types = {t: rules.case_for(t, cfg["rail"]) for t in ("P2P", "P2M")}
    C.import_from_iterable([(t, c, TAT[c], RATE, rules.TAT_FACT_IDS[c]) for t, c in types.items()], ("TGE_RECON", "TAT_RULES"))
    C.import_from_iterable([(c, cat) for cat, codes in cfg["response_codes"].items() for c in codes], ("TGE_RECON", "RESP_CODE_MAP"))
    C.import_from_iterable([(k["kind"], k["pattern"], k["priority"]) for k in cfg["narration_kinds"]], ("TGE_RECON", "NARRATION_KIND"))
    for f in pipeline.RECON_STEPS:
        run_sql_file(C, f)


def checks(C) -> list[tuple[str, bool, str]]:
    uid = {name: t[0] for name, t in CASES.items()}
    exc = {r[0]: r for r in C.execute('SELECT "UPI_TXN_ID", "CLASS", "STATUS", "REVERSAL_DT", "DEBIT_TOTAL_PAISE", "REVERSED_PAISE" '
                                      'FROM "TGE_RECON"."EXCEPTIONS"').fetchall()}
    wq = {r[0]: r for r in C.execute('SELECT "UPI_TXN_ID", "QUEUE_RANK", "TAT_STATE", "NEW_ACCRUAL_24H_PAISE", "DAYS_TO_DEADLINE" '
                                     'FROM "TGE_RECON"."WORK_QUEUE"').fetchall()}
    rank = {name: wq[u][1] for name, u in uid.items() if u in wq}
    out = []

    def check(name, ok, seen):
        out.append((name, bool(ok), str(seen)))

    p = exc[uid["partial"]]
    check("partial reversal stays OPEN, with no reversal date", p[2] == "OPEN" and p[3] is None, p)
    check("partial reversal records 40000 of 100000 paise", int(p[4]) == 100000 and int(p[5]) == 40000, p)
    i = exc[uid["instalments"]]
    check("reversal in two instalments closes on the last one", i[2] == "REVERSED" and str(i[3]) == "2026-10-02", i)
    d = exc[uid["double_debit_failed"]]
    check("double debit on a failed payment is DEBIT_NO_CREDIT, not DUPLICATE_POSTING", d[1] == "DEBIT_NO_CREDIT", d)
    check("double debit: both debits count towards the reversal due", int(d[4]) == 200000, d)
    check("a full reversal is REVERSED", exc[uid["full"]][2] == "REVERSED", exc[uid["full"]])
    check("double debit on a SUCCESS payment is still DUPLICATE_POSTING", exc[uid["duplicate_ok"]][1] == "DUPLICATE_POSTING",
          exc[uid["duplicate_ok"]])
    check("every accruing case adds the same paise tomorrow",
          {int(wq[uid[n]][3]) for n in ("overdue_old", "overdue_new_big", "at_risk")} == {RATE},
          [wq[uid[n]][3] for n in ("overdue_old", "overdue_new_big", "at_risk")])
    check("longest wait outranks larger amount among accruing cases", rank["overdue_old"] < rank["overdue_new_big"], rank)
    check("a case that starts accruing tomorrow outranks compensation that adds nothing", rank["at_risk"] < rank["comp_due"], rank)
    check("compensation owed outranks a case still within TAT", rank["comp_due"] < rank["within_tat"], rank)
    check("a case within TAT outranks a break with no TAT clock", rank["within_tat"] < rank["duplicate_ok"], rank)
    check("deadline countdown: past deadline is negative", int(wq[uid["overdue_old"]][4]) == 1 + P2P_TAT - 8, wq[uid["overdue_old"]])
    check("deadline countdown: deadline on the cut-off date is 0", int(wq[uid["at_risk"]][4]) == 0, wq[uid["at_risk"]])
    return out


def main():
    load_dotenv(ROOT / ".env")
    C = pipeline.connect()
    try:
        load(C)
        res = checks(C)
    finally:
        for s in SCHEMAS:
            C.execute(f'DROP SCHEMA IF EXISTS "TGE_{s}" CASCADE')
        left = C.execute("SELECT COUNT(*) FROM EXA_SCHEMAS WHERE SCHEMA_NAME LIKE 'TGE\\_%' ESCAPE '\\'").fetchval()
        C.close()
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    passed = sum(ok for _, ok, _ in res)
    body = ["# Verifier report: V5 (edge cases through the real SQL)\n", "```",
            f"PHASE: V5   COMMIT: {r.stdout.strip()} plus working-tree changes   DATE: {dt.datetime.now().astimezone().isoformat(timespec='seconds')}",
            f"DATA: {len(CASES)} handcrafted SYNTHETIC transactions in throwaway TGE_* schemas   HOST: {pipeline.host_label()}", "```",
            "| Check | Verdict | Seen |", "|---|---|---|",
            *[f"| {n} | {'PASS' if ok else 'FAIL'} | `{seen[:110].replace('|', '/')}` |" for n, ok, seen in res],
            f"\nThrowaway schemas left behind: {left}.", f"\n**OVERALL: {'PASS' if passed == len(res) and not left else 'FAIL'}** ({passed} of {len(res)})"]
    rep = ROOT / "reports" / f"verifier_V5_{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}.md"
    rep.write_text("\n".join(body), encoding="utf-8")
    print(rep)
    print("\n".join(body[5:]))
    sys.exit(0 if passed == len(res) and not left else 1)


if __name__ == "__main__":
    main()
