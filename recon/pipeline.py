"""TAT Guard pipeline: load synthetic data into Exasol, run the reconciliation, ingest late files.

    python recon/pipeline.py load   --data data/1m      # schemas + bulk load + settings
    python recon/pipeline.py recon                     # passes 1-4, classify, penalty views (timed)
    python recon/pipeline.py ingest-pending --data data/1m   # the late settlement file arrives
    python recon/pipeline.py all    --data data/1m

Ground truth is NOT loaded here (03_VERIFIER.md V2: only verify/ may touch the ground-truth table). After `load`, run
    python verify/v1_load.py --data data/1m          # loads ground truth + checks row counts

Credentials come only from env vars EXA_DSN, EXA_USER, EXA_PASSWORD. A TLS certificate fingerprint, if needed,
goes inside EXA_DSN as pyexasol 2.4.1 expects: hostname[/fingerprint][:port]. EXA_ENCRYPTION=0 disables TLS.
Every step is timed with time.perf_counter around the Exasol call and written to RECON.RUN_LOG and
reports/timings.csv. These are the only timing numbers allowed in README/deck ([MEASURED]).
Set TATGUARD_HOST_LABEL (e.g. "exasol-personal-local") so timings.csv records which instance produced them.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import pathlib
import sys
import time
import uuid

import pyexasol
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from recon import rules  # noqa: E402

SQL = ROOT / "sql"
RECON_STEPS = ["20_udfs.sql", "10_match_pass1.sql", "10_match_pass2.sql", "10_match_pass3.sql",
               "10_match_pass4.sql", "15_classify.sql", "30_penalty_view.sql"]
LOADS = [  # (csv file, target table)
    ("switch_log.csv", "RAW.SWITCH_LOG"),
    ("npci_settlement.csv", "RAW.NPCI_SETTLEMENT"),
    ("cbs_ledger.csv", "RAW.CBS_LEDGER"),
    ("settlement_file_log.csv", "RAW.SETTLEMENT_FILE_LOG"),
]
IMPORT_PARAMS = {"skip": 1}


def connect(user: str | None = None, password: str | None = None) -> pyexasol.ExaConnection:
    """Admin connection by default; pass user AND password for another user (e.g. the read-only agent user)."""
    if (user is None) != (password is None):
        raise ValueError("pass both user and password, or neither")   # never mix one user with another's password
    kw = dict(dsn=os.environ["EXA_DSN"], user=os.environ["EXA_USER"] if user is None else user,
              password=os.environ["EXA_PASSWORD"] if password is None else password, compression=True)
    if os.environ.get("EXA_ENCRYPTION", "1") == "0":
        kw["encryption"] = False
    return pyexasol.connect(**kw)


class Timer:
    def __init__(self, C, run_id: str, scale: str):
        self.C, self.run_id, self.scale, self.rows = C, run_id, scale, []

    def step(self, name: str, fn, count_sql: str | None = None):
        t0 = dt.datetime.now()
        p0 = time.perf_counter()
        fn()
        ms = round((time.perf_counter() - p0) * 1000)
        n = self.C.execute(count_sql).fetchval() if count_sql else None
        self.rows.append((self.run_id, name, t0, dt.datetime.now(), ms, n))
        print(f"  {name:<34} {ms:>9} ms   rows={n}")
        return ms

    def flush(self):
        self.C.execute("CREATE TABLE IF NOT EXISTS RECON.RUN_LOG (RUN_ID VARCHAR(40), STEP VARCHAR(100), "
                       "STARTED_TS TIMESTAMP, FINISHED_TS TIMESTAMP, DURATION_MS DECIMAL(18,0), ROW_COUNT DECIMAL(18,0))")
        if self.rows:
            self.C.import_from_iterable(
                [(r[0], r[1], r[2].strftime("%Y-%m-%d %H:%M:%S"), r[3].strftime("%Y-%m-%d %H:%M:%S"), r[4], r[5])
                 for r in self.rows], ("RECON", "RUN_LOG"))
        out = ROOT / "reports" / "timings.csv"
        new = not out.exists()
        with open(out, "a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(["run_id", "scale", "step", "started", "duration_ms", "rows", "host"])
            for r in self.rows:
                w.writerow([r[0], self.scale, r[1], r[2].isoformat(timespec="seconds"), r[4], r[5], host_label()])
        self.rows = []


def host_label() -> str:
    # no default instance name: a timing row must not claim a platform nobody recorded
    return os.environ.get("TATGUARD_HOST_LABEL", "UNLABELLED")


def script(C, path: pathlib.Path):
    C.execute_sql_script(path.read_text(encoding="utf-8"))


def load_settings(C, manifest: dict):
    cfg = yaml.safe_load(open(ROOT / "recon" / "config.yaml", encoding="utf-8"))
    m = cfg["matching"]
    settings = {"as_of": manifest["as_of"].replace("T", " "), "pass2_window_s": m["pass2_window_s"],
                "pass4_window_s": m["pass4_window_s"], "pass4_threshold": m["pass4_threshold"],
                "ref_pattern": m["ref_pattern"], "rail": cfg["rail"],
                **{f"pass4_w_{k}": v for k, v in m["pass4_weights"].items()}}
    C.execute("TRUNCATE TABLE RECON.SETTINGS")
    C.import_from_iterable([(k, str(v)) for k, v in settings.items()], ("RECON", "SETTINGS"))
    # one TAT rule per TXN_TYPE present in the loaded data; case_for raises if a type has no rule in facts.yaml,
    # so no type can silently drop out of the inner join in RECON.PENALTY_EXPOSURE
    tat = rules.tat_days()
    types = [r[0] for r in C.execute('SELECT DISTINCT "TXN_TYPE" FROM "RAW"."NPCI_SETTLEMENT" '
                                     'WHERE "TXN_TYPE" IS NOT NULL ORDER BY 1').fetchall()]
    if not types:
        raise SystemExit("RAW.NPCI_SETTLEMENT has no TXN_TYPE values; load data first")
    cases = {t: rules.case_for(t, cfg["rail"]) for t in types}
    rows = [(t, c, tat[c], rules.paise_per_day(), rules.TAT_FACT_IDS[c]) for t, c in cases.items()]
    C.execute("TRUNCATE TABLE RECON.TAT_RULES")
    C.import_from_iterable(rows, ("RECON", "TAT_RULES"))
    C.execute("TRUNCATE TABLE RECON.RESP_CODE_MAP")
    C.import_from_iterable([(c, cat) for cat, codes in cfg["response_codes"].items() for c in codes],
                           ("RECON", "RESP_CODE_MAP"))
    C.execute("TRUNCATE TABLE RECON.NARRATION_KIND")
    C.import_from_iterable([(k["kind"], k["pattern"], k["priority"]) for k in cfg["narration_kinds"]],
                           ("RECON", "NARRATION_KIND"))


def cmd_load(C, T: Timer, data: pathlib.Path, reset_audit: bool = False):
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    if not manifest.get("synthetic"):
        raise SystemExit("refusing to load: manifest is not marked synthetic")
    T.step("schemas", lambda: script(C, SQL / "00_schemas.sql"))
    if reset_audit:   # demo resets only: the audit tables are append-only otherwise (CREATE TABLE IF NOT EXISTS)
        for t in ("PROPOSED_ACTIONS", "ACTION_LOG"):
            C.execute(f'TRUNCATE TABLE "AUDIT"."{t}"')
        print("  AUDIT.PROPOSED_ACTIONS and AUDIT.ACTION_LOG truncated (--reset-audit)")
    for fname, table in LOADS:
        schema, name = table.split(".")
        T.step(f"load {table}", lambda f=fname, s=schema, n=name: C.import_from_file(str(data / f), (s, n), IMPORT_PARAMS),
               f'SELECT COUNT(*) FROM "{schema}"."{name}"')
    T.step("settings", lambda: load_settings(C, manifest))


def cmd_recon(C, T: Timer):
    total = 0
    missing = [f for f in RECON_STEPS if not (SQL / f).exists()]
    if missing:
        raise SystemExit(f"missing SQL step(s): {missing}")
    for f in RECON_STEPS:
        p = SQL / f
        total += T.step(f"recon {f}", lambda p=p: script(C, p))
    print(f"  {'TOTAL recon':<34} {total:>9} ms")
    for name, q in [("exceptions", 'SELECT COUNT(*) FROM "RECON"."EXCEPTIONS"'),
                    ("open queue", 'SELECT COUNT(*) FROM "RECON"."WORK_QUEUE"')]:
        print(f"  {name}: {C.execute(q).fetchval()}")


def cmd_ingest_pending(C, T: Timer, data: pathlib.Path):
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    f = data / "npci_settlement_pending.csv"
    T.step("ingest pending NPCI file", lambda: C.import_from_file(str(f), ("RAW", "NPCI_SETTLEMENT"), IMPORT_PARAMS),
           'SELECT COUNT(*) FROM "RAW"."NPCI_SETTLEMENT"')
    for p in manifest["pending_files"]:
        C.execute('UPDATE "RAW"."SETTLEMENT_FILE_LOG" SET "ARRIVED_TS" = {ts}, "RECORD_COUNT" = {n!d} '
                  'WHERE "SETTLEMENT_DT" = {d} AND "CYCLE_NO" = {c!d}',
                  {"ts": p["ARRIVES_TS"].replace("T", " "), "n": p["RECORD_COUNT"], "d": p["SETTLEMENT_DT"], "c": p["CYCLE_NO"]})
        C.execute('UPDATE "RECON"."SETTINGS" SET "PARAM_VALUE" = {ts} WHERE "PARAM_NAME" = \'as_of\' AND "PARAM_VALUE" < {ts}',
                  {"ts": p["ARRIVES_TS"].replace("T", " ")})


def main(argv=None):
    ap = argparse.ArgumentParser(description="TAT Guard pipeline")
    ap.add_argument("command", choices=["load", "recon", "ingest-pending", "all"])
    ap.add_argument("--data")
    ap.add_argument("--scale", default=None, help="label for timings.csv (default: rows from manifest)")
    ap.add_argument("--reset-audit", action="store_true",
                    help="with load: also empty AUDIT.PROPOSED_ACTIONS and AUDIT.ACTION_LOG (demo resets only)")
    a = ap.parse_args(argv)
    data = pathlib.Path(a.data) if a.data else None
    scale = a.scale
    if scale is None and data:
        scale = str(json.loads((data / "manifest.json").read_text(encoding="utf-8"))["rows"])
    C = connect()
    T = Timer(C, uuid.uuid4().hex[:12], scale or "")
    try:
        if a.command in ("load", "all"):
            cmd_load(C, T, data, a.reset_audit)
        if a.command == "ingest-pending":
            cmd_ingest_pending(C, T, data)
        if a.command in ("recon", "all", "ingest-pending"):
            cmd_recon(C, T)
    finally:
        T.flush()
        C.close()


if __name__ == "__main__":
    main()
