"""The Live page's engine: everything a visitor does runs as real statements on Exasol, one job at a time.

A payment is the rows the generator would write for that outcome, inserted into RAW; the full reconciliation then runs
over every row in the database, and the verdict is read back from RECON. Nothing here tells the matcher what was injected.
The scenario goes to VERIFIER, which the matcher and the agent never read, so the page can compare the verdict with
what was injected and show a real result, including a wrong one.

One worker thread owns every write, so visitors cannot collide: payments that arrive during a run share the next run.
The clock is RECON.SETTINGS.as_of. Penalties are a view over it, so moving the clock moves every rupee figure at once.

All timings and row counts shown come from the statements that ran, and the execution plans from
EXA_USER_PROFILE_LAST_DAY. Data is SYNTHETIC: visitors make it, but no real account or payment is involved.
"""
from __future__ import annotations

import collections
import copy
import datetime as dt
import json
import os
import pathlib
import random
import re
import secrets
import sys
import threading
import time
import uuid

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent import actions  # noqa: E402
from recon import pipeline  # noqa: E402
from ui import api  # noqa: E402
from verify.v2_accuracy import CONFUSION_SQL  # noqa: E402

GEN = yaml.safe_load(open(ROOT / "generator" / "config.yaml", encoding="utf-8"))
NARR, RESP, IDS = GEN["narration"], GEN["responses"], GEN["ids"]
SECONDS_PER_CYCLE = 86400 // GEN["settlement"]["cycles_per_day"]
RRN_DIGITS = int(IDS["rrn_digits"])

# key -> what the page offers, and the class a correct reconciliation must find. None = must stay clean.
SCENARIOS = {
    "debit_no_credit": {"label": "Money leaves, payee gets nothing", "expected": "DEBIT_NO_CREDIT",
                        "hint": "The app times out. NPCI fails it. The ledger still debits. The TAT clock starts."},
    "duplicate": {"label": "Customer is debited twice", "expected": "DUPLICATE_POSTING",
                  "hint": "The payment succeeds, but the ledger posts the debit a second time."},
    "amount_mismatch": {"label": "Ledger debits the wrong amount", "expected": "AMOUNT_MISMATCH",
                        "hint": "The payment succeeds, but the ledger amount differs by ₹1."},
    "no_debit": {"label": "Payee is paid, customer is never debited", "expected": "NPCI_SUCCESS_NO_CBS",
                 "hint": "NPCI says success but no debit exists. The bank is out of pocket."},
    "clean": {"label": "Nothing goes wrong", "expected": None,
              "hint": "All three systems agree. It must not be flagged."},
    "messy_narration": {"label": "Clean payment, messy ledger note", "expected": None,
                        "hint": "The reference is buried in free text with decoy numbers. Only the Python UDF can read it."},
    "no_reference": {"label": "Clean payment, no reference in ledger", "expected": None,
                     "hint": "The ledger note has no reference at all. Pass 4 has to score its way to a match."},
    "switch_id_missing": {"label": "Clean payment, switch lost the id", "expected": None,
                          "hint": "The switch row has no transaction id. Pass 2 has to match on RRN, amount and time."},
}
STEPS = {   # pipeline step -> (key, label on the page)
    "recon 20_udfs.sql": ("udf", "Install Python UDF"),
    "recon 10_match_pass1.sql": ("pass1", "Pass 1: join on transaction id"),
    "recon 10_match_pass2.sql": ("pass2", "Pass 2: RRN, amount and time"),
    "recon 10_match_pass3.sql": ("pass3", "Pass 3: Python UDF reads ledger notes"),
    "recon 10_match_pass4.sql": ("pass4", "Pass 4: fuzzy score, no reference"),
    "recon 15_classify.sql": ("classify", "Classify every break"),
    "recon 30_penalty_view.sql": ("clock", "Start the TAT clock"),
}
PAYEE_RE = re.compile(r"^[A-Za-z][A-Za-z .']{0,39}$")
BANK_RE = re.compile(r"^BNK\d{2}$")
ACTION_ID_RE = re.compile(r"^PA-[0-9A-F]{12}$")
ACTORS = ("You", "Pipeline", "AI analyst", "Approver", "System")
MAX_AMOUNT_RS = int(GEN["txn"]["amount_max_paise"]) // 100
MAX_CLOCK_DAYS = 30        # DESIGN: how far past the dataset's cut-off visitors may push the clock
MAX_STORM_ROWS = 200_000   # DESIGN: one outage must not outgrow the demo instance's memory
MAX_LIVE_ROWS = 1_000_000  # DESIGN: a reset is due long before this
FEED_SIZE = 300
BATCH_SIZE = 20            # DESIGN: payments that may share one reconciliation run
JOBS_KEPT = 200


class Busy(ValueError):
    pass


def _ts(v) -> dt.datetime:
    return dt.datetime.strptime(str(v)[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")


def _fmt(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M:%S")


def payee_token(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", name.upper())[:16] or "PAYEE"


def validate_payment(body: dict) -> dict:
    """The page's form, checked before anything reaches SQL. Raises ValueError with a message for the visitor."""
    scenario = str(body.get("scenario", ""))
    if scenario not in SCENARIOS:
        raise ValueError("Pick what should happen to this payment.")
    payee = str(body.get("payee", "")).strip()
    if not PAYEE_RE.match(payee):
        raise ValueError("Payee name: letters, spaces, dots and apostrophes, up to 40 characters.")
    txn_type = str(body.get("txn_type", ""))
    if txn_type not in GEN["txn"]["type_mix"]:
        raise ValueError("Payment type must be P2P or P2M.")
    bank = str(body.get("bank", ""))
    if not BANK_RE.match(bank) or not 1 <= int(bank[3:]) <= int(IDS["counterparty_banks"]):
        raise ValueError("Pick a payee bank.")
    try:
        paise = round(float(body.get("amount")) * 100)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Enter an amount in rupees.") from None
    if not 100 <= paise <= MAX_AMOUNT_RS * 100:
        raise ValueError(f"Amount must be between ₹1 and ₹{MAX_AMOUNT_RS:,}.")
    return {"scenario": scenario, "payee": payee, "txn_type": txn_type, "bank": bank, "paise": paise}


def build_rows(p: dict, ts: dt.datetime, uid: str, rrn: str) -> dict:
    """The rows one payment writes, by the same rules as generator/generate.py. Only the rows differ per scenario;
    every scenario goes through the same reconciliation."""
    sc, rng = p["scenario"], random.SystemRandom()
    dnc = sc == "debit_no_credit"
    payee = payee_token(p["payee"])
    sw_status, resp = "SUCCESS", RESP["success"]
    if dnc:
        sw_status = rng.choices(RESP["dnc_switch_status"], RESP["dnc_switch_status_weights"])[0]
        resp = rng.choice(RESP["technical_decline"])
    day, cycle = ts.date(), ts.hour * 3600 // SECONDS_PER_CYCLE + 1
    fields = {"rrn": rrn, "payee": payee, "pbank": p["bank"], "date": ts.strftime("%d%m%Y"),
              "mob": "9" + "".join(rng.choices("0123456789", k=9)), "txnid": uid}
    tmpl = {"messy_narration": "messy", "no_reference": "noref"}.get(sc, "clean")
    narration = rng.choice(NARR[tmpl]).format(**fields)
    amount = p["paise"]
    ledger_amount = amount + 100 if sc == "amount_mismatch" else amount
    acct = "XXXXXXXX" + "".join(rng.choices("0123456789", k=4))
    post_ts = ts + dt.timedelta(seconds=rng.randint(5, int(GEN["timing"]["cbs_post_lag_s"])))
    switch = {"UPI_TXN_ID": None if sc == "switch_id_missing" else uid, "RRN": rrn, "TXN_TS": _fmt(ts), "AMOUNT_PAISE": amount,
              "STATUS": sw_status, "RESP_CODE": resp, "CHANNEL": "APP"}
    npci = {"UPI_TXN_ID": uid, "RRN": rrn, "TXN_TS": _fmt(ts + dt.timedelta(seconds=rng.randint(0, GEN["timing"]["npci_ts_jitter_s"]))),
            "SETTLEMENT_DT": str(day), "CYCLE_NO": cycle, "AMOUNT_PAISE": amount, "PAYER_BANK": IDS["bank_code"],
            "PAYEE_BANK": p["bank"], "TXN_TYPE": p["txn_type"], "RESP_CODE": resp, "STATUS": "FAILED" if dnc else "SUCCESS"}
    ledger = []
    if sc != "no_debit":
        entry = {"CBS_ENTRY_ID": "L" + uuid.uuid4().hex[:16].upper(), "ACCOUNT_NO_MASKED": acct, "POST_TS": _fmt(post_ts), "DR_CR": "DR",
                 "AMOUNT_PAISE": ledger_amount, "NARRATION": narration}
        ledger.append(entry)
        if sc == "duplicate":
            second = post_ts + dt.timedelta(seconds=int(GEN["timing"]["duplicate_extra_lag_s"]))
            ledger.append({**entry, "CBS_ENTRY_ID": "L" + uuid.uuid4().hex[:16].upper(), "POST_TS": _fmt(second)})
    return {"switch": switch, "npci": npci, "ledger": ledger}


INSERTS = {
    "switch": ('"RAW"."SWITCH_LOG"', ("UPI_TXN_ID", "RRN", "TXN_TS", "AMOUNT_PAISE", "STATUS", "RESP_CODE", "CHANNEL")),
    "npci": ('"RAW"."NPCI_SETTLEMENT"', ("UPI_TXN_ID", "RRN", "TXN_TS", "SETTLEMENT_DT", "CYCLE_NO", "AMOUNT_PAISE", "PAYER_BANK",
                                         "PAYEE_BANK", "TXN_TYPE", "RESP_CODE", "STATUS")),
    "ledger": ('"RAW"."CBS_LEDGER"', ("CBS_ENTRY_ID", "ACCOUNT_NO_MASKED", "POST_TS", "DR_CR", "AMOUNT_PAISE", "NARRATION")),
}


def insert_sql(C, kind: str, row: dict) -> str:
    table, cols = INSERTS[kind]
    marks = ", ".join("NULL" if row[c] is None else C.format.format("{v}", v=str(row[c])) for c in cols)
    return f'INSERT INTO {table} ({", ".join(chr(34) + c + chr(34) for c in cols)}) VALUES ({marks})'


def plain_sql(sql: str, limit: int = 900) -> str:
    """SQL as shown in the feed: comments gone, whitespace tidied, cut at the end of the first statement."""
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    text = "\n".join(lines).strip().split(";\n")[0].strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "\n…"


PLAN_PARTS = ("SCAN", "JOIN", "OUTER JOIN", "FULL JOIN", "NOT EXISTS", "EXISTS", "GROUP BY", "SORT", "INSERT", "SCRIPT")


def plan_rows(parts: list) -> list[dict]:
    """Rows of EXA_USER_PROFILE_LAST_DAY as the feed shows them: the parts that say how the data moved, plus anything slow."""
    keep = [p for p in parts if p[3] != "DUAL" and not str(p[3] or "").startswith("tmp_")
            and (any(str(p[2]).startswith(n) for n in PLAN_PARTS) or (p[6] is not None and float(p[6]) >= 0.05))]
    return [{"part": p[2], "object": p[3], "rows_in": None if p[4] is None else int(float(p[4])),
             "rows_out": None if p[5] is None else int(float(p[5])), "ms": None if p[6] is None else round(float(p[6]) * 1000)}
            for p in keep][:14]


class Engine:
    def __init__(self, writer, fast, q, data_dir: pathlib.Path, idle_reset_s: int = 0):
        """writer: Db for jobs, held for a whole reconciliation. fast: Db for short writes and VERIFIER reads while a
        run holds the writer. q: the read-only query function behind the page."""
        self.writer, self.fast, self.q, self.data = writer, fast, q, pathlib.Path(data_dir)
        self.lock, self.wake = threading.Lock(), threading.Condition()
        self.pending, self.jobs = collections.deque(), collections.OrderedDict()
        self.feed, self.seq = collections.deque(maxlen=FEED_SIZE), 0
        self.run_state, self.last_run, self.working = None, None, None
        self.kpi_cache, self.kpi_at = None, 0.0
        self.idle_reset_s, self.last_active, self.dirty = idle_reset_s, time.time(), False
        self.stop = False
        self.manifest = json.loads((self.data / "manifest.json").read_text(encoding="utf-8")) if (self.data / "manifest.json").exists() else {}
        threading.Thread(target=self._loop, daemon=True, name="live-worker").start()
        if idle_reset_s:
            threading.Thread(target=self._idle_loop, daemon=True, name="live-idle").start()

    # ------------------------------------------------------------------ feed
    def log(self, actor: str, title: str, sql: str | None = None, ms: int | None = None, rows=None, plan=None, tone: str = "",
            replaces: int | None = None) -> int:
        """Add one line to the rail. replaces: an earlier line this one updates in place (a step gains its plan)."""
        with self.lock:
            self.seq += 1
            at = dt.datetime.now().strftime("%H:%M:%S")
            if replaces:
                old = next((e for e in self.feed if e["seq"] == replaces), None)
                if old:
                    at = old["at"]
                    self.feed.remove(old)
            self.feed.append({"seq": self.seq, "at": at, "actor": actor, "title": title, "sql": sql, "ms": ms, "rows": rows,
                              "plan": plan, "tone": tone, "replaces": replaces})
            return self.seq

    def _exec(self, C, sql: str, actor: str, title: str, params: dict | None = None):
        """Run one statement and put the exact text, its time and its row count in the feed."""
        text = C.format.format(sql, **params) if params else sql
        t0 = time.perf_counter()
        st = C.execute(text)
        ms = round((time.perf_counter() - t0) * 1000)
        self.log(actor, title, plain_sql(text), ms, st.rowcount())
        return st

    # ------------------------------------------------------------------ jobs
    def _new_job(self, kind: str, session: str, title: str, **extra) -> dict:
        job = {"id": "J" + uuid.uuid4().hex[:10], "kind": kind, "session": session, "title": title, "state": "queued",
               "created": time.time(), "error": None, **extra}
        with self.wake:
            self.jobs[job["id"]] = job
            while len(self.jobs) > JOBS_KEPT:
                self.jobs.popitem(last=False)
            self.pending.append(job)
            self.last_active = time.time()
            self.wake.notify_all()
        return job

    def _queue_len(self) -> int:
        with self.wake:
            return len(self.pending)

    def pay(self, session: str, body: dict) -> dict:
        return self._public(self._new_job("payment", session, f"Payment to {validate_payment(body)['payee']}", payment=validate_payment(body)))

    def storm(self, session: str, body: dict) -> dict:
        try:
            rows, pct = int(body.get("rows")), float(body.get("fail_pct"))
        except (TypeError, ValueError):
            raise ValueError("Pick how many payments and what share fail.") from None
        bank = str(body.get("bank", ""))
        if not 1000 <= rows <= MAX_STORM_ROWS:
            raise ValueError(f"An outage can be 1,000 to {MAX_STORM_ROWS:,} payments.")
        if not 0.1 <= pct <= 50:
            raise ValueError("Between 0.1% and 50% of the payments can fail.")
        if not BANK_RE.match(bank):
            raise ValueError("Pick a payee bank.")
        return self._public(self._new_job("storm", session, f"Outage at {bank}: {rows:,} payments", rows=rows, fail_pct=pct, bank=bank))

    def move_clock(self, session: str, days: int) -> dict:
        if days not in (1, 2, 5):
            raise ValueError("The clock moves 1, 2 or 5 days.")
        return self._public(self._new_job("clock", session, f"Clock forward {days} day{'s' if days > 1 else ''}", days=days))

    def late_file(self, session: str) -> dict:
        return self._public(self._new_job("late_file", session, "The late NPCI file arrives"))

    def decide(self, session: str, action_id: str, approve: bool, user: str) -> dict:
        if not ACTION_ID_RE.match(action_id):
            raise ValueError("bad action id")
        return self._public(self._new_job("decision", session, f"{'Approve' if approve else 'Reject'} {action_id}",
                                          action_id=action_id, approve=approve, user=user))

    def reset(self, session: str = "system") -> dict:
        return self._public(self._new_job("reset", session, "Reset the demo"))

    @staticmethod
    def _public(job: dict) -> dict:
        return {k: v for k, v in copy.deepcopy(job).items() if k not in ("session", "user")}

    # ------------------------------------------------------------------ worker
    def _take(self) -> list[dict]:
        with self.wake:
            while not self.pending and not self.stop:
                self.wake.wait(1)
            if self.stop:
                return []
            batch = [self.pending.popleft()]
            while batch[0]["kind"] == "payment" and self.pending and self.pending[0]["kind"] == "payment" and len(batch) < BATCH_SIZE:
                batch.append(self.pending.popleft())
            return batch

    def _loop(self):
        handlers = {"payment": self._do_payments, "storm": self._do_storm, "clock": self._do_clock,
                    "late_file": self._do_late_file, "decision": self._do_decision, "reset": self._do_reset}
        while not self.stop:
            batch = self._take()
            if not batch:
                continue
            self.working = batch[0]["title"]
            try:
                self.writer.run(lambda C: handlers[batch[0]["kind"]](C, batch))
            except Exception as e:  # shown to the visitor; the worker must outlive any one job
                msg = f"{type(e).__name__}: {e}"[:400]
                self.log("System", "That job failed", msg, tone="bad")
                for job in batch:
                    job.update(state="failed", error=msg)
            finally:
                self.run_state, self.working = None, None
                self.kpi_cache = None     # what the job changed shows on the next poll

    def _as_of(self, C) -> dt.datetime:
        return _ts(C.execute("""SELECT "PARAM_VALUE" FROM "RECON"."SETTINGS" WHERE "PARAM_NAME" = 'as_of'""").fetchval())

    def _set_as_of(self, C, ts: dt.datetime):
        C.execute("""UPDATE "RECON"."SETTINGS" SET "PARAM_VALUE" = {t} WHERE "PARAM_NAME" = 'as_of'""", {"t": _fmt(ts)})

    def _new_rrn(self, C) -> str:
        while True:
            rrn = str(secrets.randbelow(10 ** RRN_DIGITS)).zfill(RRN_DIGITS)
            if not C.execute('SELECT COUNT(*) FROM "RAW"."SWITCH_LOG" WHERE "RRN" = {r}', {"r": rrn}).fetchval():
                return rrn

    def _ensure_file(self, C, ts: dt.datetime):
        """A live payment belongs to a settlement cycle, so that cycle's file must be in the log."""
        day = ts.date()
        cycle = ts.hour * 3600 // SECONDS_PER_CYCLE + 1
        if C.execute('SELECT COUNT(*) FROM "RAW"."SETTLEMENT_FILE_LOG" WHERE "SETTLEMENT_DT" = {d} AND "CYCLE_NO" = {c!d}',
                     {"d": str(day), "c": cycle}).fetchval():
            return
        start = dt.datetime.combine(day, dt.time()) + dt.timedelta(seconds=(cycle - 1) * SECONDS_PER_CYCLE)
        end = start + dt.timedelta(seconds=SECONDS_PER_CYCLE)
        expected = end + dt.timedelta(minutes=int(GEN["settlement"]["expected_lag_minutes"]))
        C.execute("""INSERT INTO "RAW"."SETTLEMENT_FILE_LOG" VALUES ({d}, {c!d}, {s}, {e}, {x}, {a}, 0)""",
                  {"d": str(day), "c": cycle, "s": _fmt(start), "e": _fmt(end), "x": _fmt(expected), "a": _fmt(min(ts, expected))})

    @staticmethod
    def _step_sql(key: str) -> str:
        name = next(n for n, (k, _) in STEPS.items() if k == key)
        return plain_sql((pipeline.SQL / name.split(" ", 1)[1]).read_text(encoding="utf-8"))

    def _tracker(self, title: str, job: dict | None = None, C=None):
        """A run's steps for the page, and the Timer callback that fills them in and posts each step to the rail as it
        finishes. With C, each step's first statement id is noted so its execution plan can be found afterwards."""
        steps = [{"key": k, "label": l, "state": "waiting", "ms": None, "rows": None, "seq": None} for k, l in STEPS.values()]
        run = {"title": title, "state": "running", "started": time.time(), "steps": steps, "total_ms": None}
        marks: dict[str, int] = {}

        def on_step(name, state, ms=None, rows=None):
            key = STEPS.get(name)
            if not key:
                return
            self.run_state = run
            if job:
                job["state"] = "reconciling"
            step = next(s for s in steps if s["key"] == key[0])
            if state == "running":
                step["state"] = "running"
                if C is not None:
                    marks[key[0]] = int(C.execute("SELECT CURRENT_STATEMENT").fetchval())
            else:
                step.update(state="done", ms=ms, rows=None if rows is None else int(rows))
                step["seq"] = self.log("Pipeline", step["label"], self._step_sql(key[0]), ms, step["rows"])
        return run, steps, marks, on_step

    def _finish_run(self, run, steps):
        run.update(state="done", total_ms=sum(s["ms"] or 0 for s in steps), finished=time.time())
        self.last_run = copy.deepcopy(run)
        self.dirty = True

    def _recon(self, C, title: str, jobs: list[dict] | None = None):
        """The real reconciliation with progress on the page. Exasol profiles each statement for the plan view."""
        run, steps, marks, on_step = self._tracker(title, C=C)
        self.run_state = run
        C.execute("ALTER SESSION SET PROFILE = 'ON'")
        T = pipeline.Timer(C, "live-" + uuid.uuid4().hex[:10], "live", on_step=on_step, csv_log=False)
        try:
            for job in jobs or []:
                job["state"] = "reconciling"
            pipeline.cmd_recon(C, T)
            T.flush()
        finally:
            C.execute("ALTER SESSION SET PROFILE = 'OFF'")
        self._finish_run(run, steps)
        self._log_plans(C, steps, marks)

    def _log_plans(self, C, steps, marks):
        """What Exasol says it did for each step: objects scanned, rows in and out, time. The reconciliation has already
        finished here, so a profile that cannot be read costs the page its plan view and nothing else."""
        try:
            C.execute("FLUSH STATISTICS")
            parts = C.execute("""SELECT "STMT_ID", "PART_ID", "PART_NAME", "OBJECT_NAME", "OBJECT_ROWS", "OUT_ROWS", "DURATION"
                                 FROM "EXA_USER_PROFILE_LAST_DAY" WHERE "SESSION_ID" = CURRENT_SESSION
                                 AND "STMT_ID" >= {s!d} ORDER BY "STMT_ID", "PART_ID" """,
                              {"s": min(marks.values())}).fetchall()
            keys = [s["key"] for s in steps if s["key"] in marks]
            bounds = {k: (marks[k], marks[keys[i + 1]] if i + 1 < len(keys) else 10 ** 12) for i, k in enumerate(keys)}
            for s in steps:
                lo, hi = bounds.get(s["key"], (0, 0))
                s["plan"] = plan_rows([p for p in parts if lo <= int(p[0]) < hi])
                self.log("Pipeline", s["label"], self._step_sql(s["key"]), s["ms"], s["rows"], s["plan"], replaces=s["seq"])
        except Exception as e:
            self.log("System", "Execution plans unavailable for this run", f"{type(e).__name__}: {e}"[:200], tone="warn")
        if self.last_run:
            self.last_run["steps"] = copy.deepcopy(steps)

    # ------------------------------------------------------------------ handlers
    def _do_payments(self, C, batch):
        ts = self._as_of(C)
        for job in batch:
            job["state"] = "writing"
            p = job["payment"]
            ts += dt.timedelta(seconds=random.randint(3, 11))     # time moves on between payments
            self._ensure_file(C, ts)
            uid, rrn = IDS["txn_id_prefix"][:2] + "L" + uuid.uuid4().hex[:16].upper(), self._new_rrn(C)
            rows = build_rows(p, ts, uid, rrn)
            job.update(uid=uid, rrn=rrn, ts=_fmt(ts))
            who = "You"
            for kind, title in (("switch", "UPI switch logged the payment"), ("npci", "NPCI settlement record arrived")):
                self._exec(C, insert_sql(C, kind, rows[kind]), who, title)
            for i, row in enumerate(rows["ledger"]):
                self._exec(C, insert_sql(C, "ledger", row), who, "Core banking posted the debit" if i == 0 else "Core banking posted a second debit")
            if not rows["ledger"]:
                self.log(who, "Core banking posted nothing", tone="warn")
            expected = SCENARIOS[p["scenario"]]["expected"]
            C.execute("""INSERT INTO "VERIFIER"."LIVE_PAYMENTS" VALUES ({u}, {r}, {s}, {e}, {t}, {c})""",
                      {"u": uid, "r": rrn, "s": p["scenario"], "e": expected, "t": job["session"], "c": _fmt(ts)})
            C.execute("""INSERT INTO "VERIFIER"."GROUND_TRUTH" ("UPI_TXN_ID", "INJECTED_BREAK", "EXPECTED_CLASS", "TXN_TYPE", "TXN_DT", "AMOUNT_PAISE")
                         VALUES ({u}, {s}, {e}, {t}, {d}, {a!d})""",
                      {"u": uid, "s": p["scenario"].upper(), "e": expected, "t": p["txn_type"], "d": str(ts.date()), "a": p["paise"]})
            job["records"] = self._read_back(C, rrn)
        self._set_as_of(C, ts)
        names = ", ".join(sorted({j["payment"]["payee"] for j in batch}))
        self._recon(C, f"Reconciling every payment in Exasol, including yours ({names})", batch)
        for job in batch:
            job["verdict"] = self._verdict(C, job)
            job["state"] = "done"
            v = job["verdict"]
            self.log("Pipeline", f"Verdict for {job['payment']['payee']}: {v['class'] or 'clean'}",
                     tone="good" if v["correct"] else "bad")

    def _read_back(self, C, rrn: str) -> dict:
        """What the page shows is what Exasol holds, not what was sent."""
        def rows(sql):
            st = C.execute(sql, {"r": rrn})
            cols = st.column_names()
            return [dict(zip(cols, [None if v is None else str(v) for v in r])) for r in st]
        return {"switch": rows("""SELECT "UPI_TXN_ID", "RRN", TO_CHAR("TXN_TS", 'YYYY-MM-DD HH24:MI:SS') AS "TIME", "AMOUNT_PAISE", "STATUS", "RESP_CODE"
                                  FROM "RAW"."SWITCH_LOG" WHERE "RRN" = {r}"""),
                "npci": rows("""SELECT "UPI_TXN_ID", "RRN", TO_CHAR("TXN_TS", 'YYYY-MM-DD HH24:MI:SS') AS "TIME", "AMOUNT_PAISE", "STATUS", "RESP_CODE", "PAYEE_BANK"
                                FROM "RAW"."NPCI_SETTLEMENT" WHERE "RRN" = {r}"""),
                "ledger": rows("""SELECT TO_CHAR("POST_TS", 'YYYY-MM-DD HH24:MI:SS') AS "TIME", "DR_CR", "AMOUNT_PAISE", "NARRATION"
                                  FROM "RAW"."CBS_LEDGER" WHERE "NARRATION" LIKE {r}""".replace("{r}", "'%' || {r} || '%'"))}

    def _verdict(self, C, job: dict) -> dict:
        st = C.execute("""SELECT t."MATCH_PASS", t."CBS_PASS", t."DR_CNT", e."EXC_ID", e."CLASS", e."STATUS", p."DEADLINE_DT", p."TAT_DAYS",
                                 p."PENALTY_PAISE", p."NEW_ACCRUAL_24H_PAISE", w."QUEUE_RANK", w."TAT_STATE"
                          FROM "RECON"."TXN_STATE" t
                          LEFT JOIN "RECON"."EXCEPTIONS" e ON e."RRN" = t."RRN"
                          LEFT JOIN "RECON"."PENALTY_EXPOSURE" p ON p."EXC_ID" = e."EXC_ID"
                          LEFT JOIN "RECON"."WORK_QUEUE" w ON w."EXC_ID" = e."EXC_ID"
                          WHERE t."RRN" = {r} LIMIT 1""", {"r": job["rrn"]})
        cols = st.column_names()
        row = st.fetchone()
        d = dict(zip(cols, [None if v is None else str(v) for v in row])) if row else {}
        expected = SCENARIOS[job["payment"]["scenario"]]["expected"]
        cls = d.get("CLASS")
        return {"class": cls, "expected": expected, "correct": cls == expected, "exc_id": d.get("EXC_ID"), "status": d.get("STATUS"),
                "match_pass": d.get("MATCH_PASS"), "cbs_pass": d.get("CBS_PASS"), "debits": d.get("DR_CNT"), "deadline": d.get("DEADLINE_DT"),
                "tat_days": d.get("TAT_DAYS"), "rank": d.get("QUEUE_RANK"), "tat_state": d.get("TAT_STATE")}

    def _do_storm(self, C, batch):
        job = batch[0]
        job["state"] = "writing"
        live = C.execute('SELECT COUNT(*) FROM "VERIFIER"."LIVE_PAYMENTS"').fetchval()
        if int(live) + job["rows"] > MAX_LIVE_ROWS:
            raise Busy("This demo has taken enough payments. It resets itself when idle.")
        as_of = self._as_of(C)
        for back in (0, 3600):
            self._ensure_file(C, as_of - dt.timedelta(seconds=back))
        tag = str(secrets.randbelow(900) + 100)
        cycle = SECONDS_PER_CYCLE // 3600
        n = {"n": job["rows"], "f": job["fail_pct"] / 100, "t": _fmt(as_of), "b": job["bank"], "tag": tag, "s": job["session"]}
        title = f"Generated {job['rows']:,} payments inside Exasol"
        self._exec(C, f"""CREATE OR REPLACE TABLE "VERIFIER"."LIVE_STORM" AS
WITH g AS (SELECT i, RANDOM() AS "RF", RANDOM() AS "RT", RANDOM() AS "RA", RANDOM() AS "RS" FROM VALUES BETWEEN 1 AND {{n!d}} AS t(i)),
x AS (SELECT 'TGS' || {{tag}} || LPAD(TO_CHAR(i), 13, '0') AS "UPI_TXN_ID", '7' || {{tag}} || LPAD(TO_CHAR(i), 8, '0') AS "RRN",
             ADD_SECONDS(CAST({{t}} AS TIMESTAMP), -FLOOR("RS" * 3600)) AS "TXN_TS",
             CAST(FLOOR(EXP(4.5 + "RA" * 4)) * 100 AS DECIMAL(18,0)) AS "AMOUNT_PAISE",
             CASE WHEN "RF" < {{f}} THEN 1 ELSE 0 END AS "FAILED", CASE WHEN "RT" < 0.62 THEN 'P2P' ELSE 'P2M' END AS "TXN_TYPE", i FROM g)
SELECT x.*, CASE WHEN "FAILED" = 1 THEN 'TD0' || TO_CHAR(MOD(i, 3) + 1) ELSE '00' END AS "RESP",
       CASE WHEN "FAILED" = 0 THEN 'SUCCESS' WHEN MOD(i, 2) = 0 THEN 'TIMEOUT' ELSE 'FAILED' END AS "SW_STATUS"
FROM x WHERE NOT EXISTS (SELECT 1 FROM "RAW"."SWITCH_LOG" s WHERE s."RRN" = x."RRN")""", "You", title, n)
        s = '"VERIFIER"."LIVE_STORM"'
        self._exec(C, f"""INSERT INTO "RAW"."SWITCH_LOG" SELECT "UPI_TXN_ID", "RRN", "TXN_TS", "AMOUNT_PAISE", "SW_STATUS", "RESP", 'APP' FROM {s}""",
                   "You", "UPI switch: outage traffic loaded")
        self._exec(C, f"""INSERT INTO "RAW"."NPCI_SETTLEMENT" SELECT "UPI_TXN_ID", "RRN", ADD_SECONDS("TXN_TS", 1), CAST("TXN_TS" AS DATE),
                          FLOOR(HOUR("TXN_TS") / {cycle}) + 1, "AMOUNT_PAISE", {{p}}, {{b}}, "TXN_TYPE", "RESP",
                          CASE WHEN "FAILED" = 1 THEN 'FAILED' ELSE 'SUCCESS' END FROM {s}""", "You", "NPCI: outage records loaded",
                   {"p": IDS["bank_code"], "b": job["bank"]})
        self._exec(C, f"""INSERT INTO "RAW"."CBS_LEDGER" SELECT 'L' || "UPI_TXN_ID", 'XXXXXXXX' || LPAD(TO_CHAR(MOD(i * 7919, 10000)), 4, '0'),
                          ADD_SECONDS("TXN_TS", 60), 'DR', "AMOUNT_PAISE", 'UPI/DR/' || "RRN" || '/P' || LPAD(TO_CHAR(i), 7, '0') || '/' || {{b}} FROM {s}""",
                   "You", "Core banking: outage debits loaded", {"b": job["bank"]})
        C.execute(f"""INSERT INTO "VERIFIER"."GROUND_TRUTH" ("UPI_TXN_ID", "INJECTED_BREAK", "EXPECTED_CLASS", "TXN_TYPE", "TXN_DT", "AMOUNT_PAISE")
                      SELECT "UPI_TXN_ID", 'OUTAGE', CASE WHEN "FAILED" = 1 THEN 'DEBIT_NO_CREDIT' END, "TXN_TYPE", CAST("TXN_TS" AS DATE), "AMOUNT_PAISE" FROM {s}""")
        C.execute(f"""INSERT INTO "VERIFIER"."LIVE_PAYMENTS" SELECT "UPI_TXN_ID", "RRN", 'OUTAGE', CASE WHEN "FAILED" = 1 THEN 'DEBIT_NO_CREDIT' END, {{t}}, "TXN_TS" FROM {s}""",
                  {"t": job["session"]})
        failed = C.execute(f'SELECT SUM("FAILED") FROM {s}').fetchval()
        C.execute(f"DROP TABLE {s}")
        job["failed"] = int(failed or 0)
        self._recon(C, f"Reconciling everything after the {job['bank']} outage", batch)
        job["state"] = "done"

    def _kpi_now(self, C) -> dict:
        r = C.execute(api.OVERVIEW_SQL["kpi"]).fetchone()
        return {"added_tomorrow": str(r[3] or 0), "owed": str(r[1] or 0), "accruing": int(r[10] or 0)}

    def _do_clock(self, C, batch):
        job = batch[0]
        job["state"] = "writing"
        as_of = self._as_of(C)
        limit = _ts(self.manifest.get("as_of", _fmt(as_of))) + dt.timedelta(days=MAX_CLOCK_DAYS)
        target = as_of + dt.timedelta(days=job["days"])
        if target > limit:
            raise Busy("The clock has gone as far as this demo allows. It resets itself when idle.")
        before = self._kpi_now(C)
        self._exec(C, """UPDATE "RECON"."SETTINGS" SET "PARAM_VALUE" = {t} WHERE "PARAM_NAME" = 'as_of'""", "You",
                   f"Bank date moved to {target:%d %b %Y}", {"t": _fmt(target)})
        t0 = time.perf_counter()
        after = self._kpi_now(C)
        ms = round((time.perf_counter() - t0) * 1000)
        self.log("Pipeline", "Penalty view recomputed every open case", plain_sql(api.OVERVIEW_SQL["kpi"], 300), ms, tone="good")
        job.update(state="done", before=before, after=after, recompute_ms=ms)
        self.dirty = True

    def _do_late_file(self, C, batch):
        job = batch[0]
        job["state"] = "writing"
        if not self.manifest.get("pending_files"):
            raise Busy("This dataset has no late file.")
        if not C.execute("""SELECT COUNT(*) FROM "RAW"."SETTLEMENT_FILE_LOG" WHERE "ARRIVED_TS" IS NULL""").fetchval():
            raise Busy("The late file has already arrived.")
        before = C.execute("""SELECT COUNT(*) FROM "RECON"."EXCEPTIONS" WHERE "CLASS" = 'LATE_FILE'""").fetchval()
        T = pipeline.Timer(C, "live-" + uuid.uuid4().hex[:10], "live", csv_log=False)
        t0 = time.perf_counter()
        pipeline.cmd_ingest_file(C, T, self.data)
        ms = round((time.perf_counter() - t0) * 1000)
        T.flush()
        rows = sum(int(p["RECORD_COUNT"]) for p in self.manifest["pending_files"])
        self.log("You", "NPCI file bulk loaded into Exasol", 'IMPORT INTO "RAW"."NPCI_SETTLEMENT" FROM CSV', ms, rows)
        C.execute("""UPDATE "VERIFIER"."GROUND_TRUTH" SET "EXPECTED_CLASS" = NULL WHERE "EXPECTED_CLASS" = 'LATE_FILE'""")
        self._recon(C, "Reconciling now the file is in", batch)
        after = C.execute("""SELECT COUNT(*) FROM "RECON"."EXCEPTIONS" WHERE "CLASS" = 'LATE_FILE'""").fetchval()
        job.update(state="done", before=int(before), after=int(after), rows=rows)

    def _do_decision(self, C, batch):
        job = batch[0]
        job["state"] = "writing"
        approve = job["approve"]
        run, steps, _, on_step = self._tracker("Reconciling after the approved posting", job)
        out = actions.decide(C, job["action_id"], approve, job["user"], on_step=on_step)
        if self.run_state is run:
            self._finish_run(run, steps)
        if out.get("executed_sql"):
            self.log("Approver", f"{job['user']} approved {job['action_id']}", plain_sql(out["executed_sql"]), tone="good")
        else:
            self.log("Approver", f"{job['user']} {'approved' if approve else 'rejected'} {job['action_id']}")
        job.update(state="done", result={k: out.get(k) for k in ("status", "before", "after", "error", "executed_sql")})
        self.dirty = True

    def _do_reset(self, C, batch):
        job = batch[0]
        job["state"] = "writing"
        T = pipeline.Timer(C, "reset-" + uuid.uuid4().hex[:10], "reset", csv_log=False)
        pipeline.cmd_load(C, T, self.data, reset_audit=True)
        C.import_from_file(str(self.data / "ground_truth.csv"), ("VERIFIER", "GROUND_TRUTH"), pipeline.IMPORT_PARAMS)
        T.flush()
        with self.lock:
            self.feed.clear()
        self._recon(C, "Reconciling the fresh dataset", batch)
        self.dirty = False
        job["state"] = "done"
        self.log("System", "Demo reset to the original dataset", tone="good")

    def _idle_loop(self):
        while not self.stop:
            time.sleep(30)
            if self.dirty and time.time() - self.last_active > self.idle_reset_s and not self._queue_len():
                self.reset()

    # ------------------------------------------------------------------ what the page polls
    def kpi(self) -> dict:
        if self.kpi_cache and time.time() - self.kpi_at < 2:
            return self.kpi_cache
        out = {k: api.one(self.q(api.OVERVIEW_SQL[k])) for k in ("kpi", "volume", "as_of", "pending", "last_recon")}
        missing = api.records(self.q(api.OVERVIEW_SQL["missing_files"]))
        cases = {k: (0 if v is None else v) for k, v in out["kpi"].items()}
        self.kpi_cache = {**cases, "TXNS": out["volume"].get("TXNS"), "EXCEPTIONS": out["volume"].get("EXCEPTIONS"), "AS_OF": out["as_of"].get("AS_OF"),
                          "PENDING": out["pending"].get("N"), "LAST_RECON_MS": out["last_recon"].get("DURATION_MS"),
                          "MISSING_FILES": missing}
        self.kpi_at = time.time()
        return self.kpi_cache

    def state(self, since: int, session: str) -> dict:
        self.last_active = time.time()
        with self.lock:
            events = [e for e in self.feed if e["seq"] > since][-60:]
            seq = self.seq
        with self.wake:
            mine = [self._public(j) for j in self.jobs.values() if j["session"] == session][-12:]
            queued = len(self.pending)
        return {"seq": seq, "events": events, "run": copy.deepcopy(self.run_state) if self.run_state and self.run_state["state"] == "running" else None,
                "working": self.working, "last_run": self.last_run, "queued": queued, "mine": mine, "kpi": self.kpi()}

    def verify(self) -> dict:
        """Live accuracy: every break the reconciliation reports against what was injected, including visitors' payments."""
        def go(C):
            rows = C.execute(CONFUSION_SQL).fetchall()
            mine = C.execute("""SELECT COUNT(*), SUM(CASE WHEN COALESCE(p."EXPECTED_CLASS", '-') = COALESCE(e."CLASS", '-') THEN 1 ELSE 0 END)
                                FROM "VERIFIER"."LIVE_PAYMENTS" p LEFT JOIN "RECON"."EXCEPTIONS" e ON e."RRN" = p."RRN" """).fetchone()
            orphan = C.execute("""SELECT COUNT(*) FROM "RECON"."EXCEPTIONS" WHERE "UPI_TXN_ID" IS NULL""").fetchval()
            return rows, mine, orphan
        t0 = time.perf_counter()
        rows, mine, orphan = self.fast.run(go)
        classes = [{"class": c, "tp": int(tp), "fp": int(fp), "fn": int(fn)} for c, tp, fp, fn in rows if c is not None]
        tp, fp, fn = (sum(c[k] for c in classes) for k in ("tp", "fp", "fn"))
        return {"classes": classes, "tp": tp, "fp": fp, "fn": fn, "live_total": int(mine[0] or 0), "live_correct": int(mine[1] or 0),
                "orphan_debits": int(orphan), "ms": round((time.perf_counter() - t0) * 1000)}

    def close(self):
        with self.wake:
            self.stop = True
            self.wake.notify_all()


def meta() -> dict:
    return {"scenarios": [{"key": k, **{f: v[f] for f in ("label", "hint", "expected")}} for k, v in SCENARIOS.items()],
            "banks": [f"BNK{i + 1:02d}" for i in range(int(IDS["counterparty_banks"]))], "max_amount": MAX_AMOUNT_RS,
            "max_storm": MAX_STORM_ROWS, "steps": [{"key": k, "label": l} for k, l in STEPS.values()]}


def data_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("TATGUARD_DATA", ROOT / "data" / "1m"))
