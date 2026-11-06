"""Run the bank: UPI traffic keeps arriving in Exasol the way it would in real life, while people work the cases.

Each tick covers the bank time since the last one, at the chosen speed:
  * payments for that window are generated inside Exasol in SQL, with the volume by hour of day, the outcome rates,
    the payee-bank mix and the amounts from generator/config.yaml, so a tick looks like a slice of the base dataset;
  * the switch and core-banking rows land in RAW at once, but each NPCI record waits for its settlement file, which
    arrives after its cycle closes (generator settlement timing), so a failed debit can only be confirmed then;
  * payee banks post the auto-reversals the generator would, on the day they fall due;
  * the full reconciliation runs, and every break it finds for the first time is stamped with the bank time it was found.

What was injected goes to VERIFIER, which the matcher and the assistant cannot read, so the page can say how fast and how
accurately breaks were caught. Data is SYNTHETIC: nothing here is a real bank, account or payment.
"""
from __future__ import annotations

import datetime as dt
import random
import re
import threading
import time

import yaml

from recon import pipeline

GEN = yaml.safe_load(open(pipeline.ROOT / "generator" / "config.yaml", encoding="utf-8"))
SPEEDS = {1: "1 bank hour a minute", 5: "5 bank hours a minute", 15: "15 bank hours a minute"}   # bank minutes per real second
OUTCOMES = ("BUSINESS_DECLINE", "DEBIT_NO_CREDIT", "NPCI_SUCCESS_NO_CBS", "AMOUNT_MISMATCH", "DUPLICATE_POSTING",
            "NARRATION_ONLY", "NARRATION_NOREF", "SWITCH_ID_MISSING")
BREAKS = ("DEBIT_NO_CREDIT", "NPCI_SUCCESS_NO_CBS", "AMOUNT_MISMATCH", "DUPLICATE_POSTING")   # outcome = class it must get
MAX_TICK_MIN = 120          # DESIGN: one tick never covers more bank time than this
MAX_ROWS = 3_500_000        # DESIGN: pause before the demo instance runs short of memory
OUTAGE_HOURS, OUTAGE_FAIL = 3, 0.05   # DESIGN: a bank outage fails 5% of that bank's payments for 3 bank hours
FILE_DELAY_HOURS = 10       # DESIGN: how late "Delay the next NPCI file" makes it
SIM_TABLES = re.compile(r"CREATE OR REPLACE TABLE (VERIFIER\.SIM_\w+ \(.*?\n\));", re.S)


def _ts(v) -> dt.datetime:
    return dt.datetime.strptime(str(v)[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")


def _fmt(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M:%S")


def _num(x: float) -> str:
    return repr(float(x))


def _cumulative(pairs) -> list[tuple[str, float]]:
    total, out = 0.0, []
    for name, p in pairs:
        total += float(p)
        out.append((name, total))
    return out


def outcome_case(rand: str) -> str:
    oc = GEN["outcomes"]
    steps = _cumulative((o, oc[o]) for o in OUTCOMES)
    return "CASE " + " ".join(f"WHEN {rand} < {_num(c)} THEN '{o}'" for o, c in steps) + " ELSE 'SUCCESS' END"


def bank_case(rand: str) -> str:
    n, a = int(GEN["ids"]["counterparty_banks"]), float(GEN["ids"]["counterparty_zipf_a"])
    w = [1 / (k ** a) for k in range(1, n + 1)]
    steps = _cumulative((f"BNK{k + 1:02d}", x / sum(w)) for k, x in enumerate(w))
    return "CASE " + " ".join(f"WHEN {rand} < {_num(c)} THEN '{b}'" for b, c in steps[:-1]) + f" ELSE '{steps[-1][0]}' END"


def reversal_case(txn_type: str, rand: str) -> str:
    """Days from T to the payee bank's auto-reversal, or NULL for one that never comes (generator reversal settings)."""
    rv = GEN["reversal"][txn_type]
    steps = _cumulative(zip(rv["lag_days"], [x / sum(rv["weights"]) for x in rv["weights"]]))
    return "CASE " + " ".join(f"WHEN {rand} < {_num(c)} THEN {'NULL' if lag == 'NEVER' else int(lag)}" for lag, c in steps) + " END"


def amount_sql(ttype: str, r_round: str, r_pick: str, r_a: str, r_b: str) -> str:
    t, ra = GEN["txn"], GEN["txn"]["round_amounts"]
    rounds = "CASE FLOOR(" + r_pick + f" * {len(ra['rupees'])}) " + " ".join(
        f"WHEN {i} THEN {v}" for i, v in enumerate(ra["rupees"][:-1])) + f" ELSE {ra['rupees'][-1]} END"
    ln = t["amount_lognormal"]
    mu = f"CASE WHEN {ttype} = 'P2P' THEN {_num(ln['P2P']['mu'])} ELSE {_num(ln['P2M']['mu'])} END"
    sigma = f"CASE WHEN {ttype} = 'P2P' THEN {_num(ln['P2P']['sigma'])} ELSE {_num(ln['P2M']['sigma'])} END"
    z = f"SQRT(-2 * LN(GREATEST({r_a}, 1E-12))) * COS(2 * PI() * {r_b})"     # Box-Muller: a standard normal draw
    paise = f"CASE WHEN {r_round} < {_num(ra['share'])} THEN {rounds} * 100 ELSE ROUND(EXP({mu} + {sigma} * {z}) * 100) END"
    return f"CAST(LEAST(GREATEST({paise}, {int(t['amount_min_paise'])}), {int(t['amount_max_paise'])}) AS DECIMAL(18,0))"


def hour_factor(t0: dt.datetime, t1: dt.datetime) -> float:
    w = GEN["calendar"]["hour_weights"]
    mean = sum(w) / len(w)
    hours, t = [], t0
    while t < t1:
        hours.append(w[t.hour])
        t += dt.timedelta(minutes=15)
    return (sum(hours) / len(hours) if hours else w[t0.hour]) / mean


class Simulator:
    def __init__(self, engine, daily_volume: int):
        self.e, self.daily = engine, max(1000, int(daily_volume))
        self.running, self.speed, self.queued = False, 5, False
        self.last_tick, self.failures = None, 0
        self.outage, self.outage_req, self.delay_req = None, None, False
        self.seq, self.late_noted = None, set()
        self.counts = {"ticks": 0, "reversals": 0, "files": 0}
        self.note, self.stats_cache, self.stats_at = None, None, 0.0
        threading.Thread(target=self._pacer, daemon=True, name="sim-pacer").start()

    # ------------------------------------------------------------------ controls (called from the web server)
    def control(self, action: str, body: dict) -> dict:
        if action == "start":
            self.speed = self._speed(body.get("speed", self.speed))
            if not self.running:
                self.running, self.last_tick, self.failures, self.note = True, time.time(), 0, None
                self.e.log("System", f"The bank is open: payments flow in at {SPEEDS[self.speed]}", tone="good")
        elif action == "pause":
            if self.running:
                self.e.log("System", "The bank is paused: no new payments until it resumes")
            self.running = False
        elif action == "speed":
            self.speed = self._speed(body.get("speed"))
        elif action == "outage":
            bank = str(body.get("bank", ""))
            if not re.fullmatch(r"BNK\d{2}", bank):
                raise ValueError("Pick a payee bank.")
            self.outage_req = bank
        elif action == "delay":
            self.delay_req = True
        else:
            raise ValueError("unknown control")
        if action in ("outage", "delay") and not self.running:
            raise ValueError("Start the bank first. Incidents happen to live traffic.")
        return self.public()

    @staticmethod
    def _speed(v) -> int:
        try:
            v = int(v)
        except (TypeError, ValueError):
            v = 0
        if v not in SPEEDS:
            raise ValueError("Pick one of the speeds offered.")
        return v

    def stop_for_reset(self):
        self.running, self.outage, self.outage_req, self.delay_req = False, None, None, False
        self.seq, self.late_noted, self.stats_cache = None, set(), None
        self.counts = {"ticks": 0, "reversals": 0, "files": 0}

    def _pacer(self):
        """Ask the worker for the next tick as soon as the last one is done."""
        while not self.e.stop:
            time.sleep(0.5)
            if self.running and not self.queued:
                self.queued = True
                self.e._new_job("sim_tick", "system", "The bank keeps running")

    # ------------------------------------------------------------------ one tick (runs on the engine's worker, writer connection)
    def ensure_tables(self, C):
        ddl = (pipeline.SQL / "00_schemas.sql").read_text(encoding="utf-8")
        for body in SIM_TABLES.findall(ddl):
            C.execute("CREATE TABLE IF NOT EXISTS " + body)

    def window(self, C, t0: dt.datetime) -> dt.datetime:
        now = time.time()
        elapsed = now - (self.last_tick or now - 10)
        self.last_tick = now
        minutes = max(1.0, min(MAX_TICK_MIN, self.speed * elapsed))
        return t0 + dt.timedelta(minutes=minutes)

    def write(self, C, t0: dt.datetime, t1: dt.datetime) -> dict:
        """Everything the outside world does between t0 and t1. The caller runs the reconciliation afterwards."""
        self.ensure_tables(C)
        rows = C.execute('SELECT COUNT(*) FROM "RAW"."SWITCH_LOG"').fetchval()
        if int(rows) >= MAX_ROWS:
            self.running = False
            raise RuntimeError("The bank has taken as many payments as this demo machine can hold. Reset the demo to continue.")
        if self.seq is None:
            self.seq = int(C.execute("""SELECT COALESCE(MAX(CAST(SUBSTR("UPI_TXN_ID", 4) AS DECIMAL(18,0))), 0)
                                        FROM "VERIFIER"."SIM_TRUTH" """).fetchval())
        if self.outage_req:
            self.outage = {"bank": self.outage_req, "until": t0 + dt.timedelta(hours=OUTAGE_HOURS)}
            self.e.log("System", f"{self.outage_req} is having an outage: {int(OUTAGE_FAIL * 100)}% of payments to it fail for the next {OUTAGE_HOURS} bank hours", tone="warn")
            self.outage_req = None
        if self.outage and self.outage["until"] <= t0:
            self.e.log("System", f"{self.outage['bank']} has recovered")
            self.outage = None
        if self.delay_req:
            self._delay_next_file(C)
        self._plan_files(C, t0, t1)
        n = round(self.daily / 1440 * (t1 - t0).total_seconds() / 60 * hour_factor(t0, t1))
        made = self._payments(C, t0, t1, n) if n > 0 else {}
        out = {"payments": sum(made.values()), "made": made}
        out["reversals"] = self._reversals(C, t1)
        out["files"] = self._files(C, t1)
        return out

    def _plan_files(self, C, t0, t1):
        st, step = GEN["settlement"], pipeline_cycle_seconds()
        start = dt.datetime.combine(t0.date(), dt.time()) + dt.timedelta(seconds=(t0.hour * 3600 + t0.minute * 60) // step * step)
        while start < t1:
            day, cycle = start.date(), (start.hour * 3600 + start.minute * 60) // step + 1
            end = start + dt.timedelta(seconds=step)
            planned = C.execute("""SELECT COUNT(*) FROM "VERIFIER"."SIM_FILES" WHERE "SETTLEMENT_DT" = {d} AND "CYCLE_NO" = {c!d}""",
                                {"d": str(day), "c": cycle}).fetchval()
            if not planned:
                expected = end + dt.timedelta(minutes=int(st["expected_lag_minutes"]))
                arrive = expected + dt.timedelta(seconds=random.randint(0, int(st["arrival_jitter_minutes"]) * 60))
                C.execute("""INSERT INTO "VERIFIER"."SIM_FILES" VALUES ({d}, {c!d}, {a})""", {"d": str(day), "c": cycle, "a": _fmt(arrive)})
                params = {"d": str(day), "c": cycle, "s": _fmt(start), "e": _fmt(end), "x": _fmt(expected)}
                logged = C.execute("""SELECT COUNT(*) FROM "RAW"."SETTLEMENT_FILE_LOG" WHERE "SETTLEMENT_DT" = {d} AND "CYCLE_NO" = {c!d}""",
                                   params).fetchval()
                if logged:      # a visitor's payment opened this cycle; its file now arrives with everyone else's
                    C.execute("""UPDATE "RAW"."SETTLEMENT_FILE_LOG" SET "ARRIVED_TS" = NULL WHERE "SETTLEMENT_DT" = {d} AND "CYCLE_NO" = {c!d}""", params)
                else:
                    C.execute("""INSERT INTO "RAW"."SETTLEMENT_FILE_LOG" VALUES ({d}, {c!d}, {s}, {e}, {x}, NULL, 0)""", params)
            start = end

    def _delay_next_file(self, C):
        nxt = C.execute("""SELECT f."SETTLEMENT_DT", f."CYCLE_NO" FROM "VERIFIER"."SIM_FILES" f
                           JOIN "RAW"."SETTLEMENT_FILE_LOG" l ON l."SETTLEMENT_DT" = f."SETTLEMENT_DT" AND l."CYCLE_NO" = f."CYCLE_NO"
                           WHERE l."ARRIVED_TS" IS NULL ORDER BY f."ARRIVE_TS" LIMIT 1""").fetchone()
        if not nxt:
            return      # no file is due yet; the request waits for the next tick
        C.execute("""UPDATE "VERIFIER"."SIM_FILES" SET "ARRIVE_TS" = ADD_HOURS("ARRIVE_TS", {h!d})
                     WHERE "SETTLEMENT_DT" = {d} AND "CYCLE_NO" = {c!d}""", {"h": FILE_DELAY_HOURS, "d": str(nxt[0]), "c": int(nxt[1])})
        self.delay_req = False
        self.e.log("System", f"NPCI is running late: the settlement file for {nxt[0]}, cycle {int(nxt[1])} will come {FILE_DELAY_HOURS} bank hours late", tone="warn")

    def _payments(self, C, t0, t1, n) -> dict:
        span = max(1, int((t1 - t0).total_seconds()))
        o = self.outage or {"bank": "-", "until": t0}
        p2p = GEN["txn"]["type_mix"]["P2P"] / sum(GEN["txn"]["type_mix"].values())
        R = ", ".join(f"RANDOM() AS R{k}" for k in range(1, 17))
        C.execute(f'CREATE OR REPLACE TABLE "VERIFIER"."SIM_RAND" AS SELECT i, {R} FROM VALUES BETWEEN 1 AND {int(n)} AS t(i)')
        seq = "CAST({s!d} + i AS VARCHAR(20))"
        C.execute(f"""CREATE OR REPLACE TABLE "VERIFIER"."SIM_BASE" AS
SELECT b.*, {amount_sql('b."TXN_TYPE"', 'b.R5', 'b.R6', 'b.R6', 'b.R7')} AS "AMOUNT_PAISE",
       CASE WHEN b."BANK" = {{ob}} AND b."TXN_TS" < CAST({{ou}} AS TIMESTAMP) AND b.R8 < {_num(OUTAGE_FAIL)} THEN 'DEBIT_NO_CREDIT'
            ELSE {outcome_case('b.R9')} END AS "OUTCOME"
FROM (SELECT r.*, 'TGB' || LPAD({seq}, 16, '0') AS "UPI_TXN_ID", '8' || LPAD({seq}, 11, '0') AS "RRN",
             ADD_SECONDS(CAST({{t0}} AS TIMESTAMP), FLOOR(r.R1 * {span})) AS "TXN_TS",
             CASE WHEN r.R2 < {_num(p2p)} THEN 'P2P' ELSE 'P2M' END AS "TXN_TYPE", {bank_case('r.R3')} AS "BANK"
      FROM "VERIFIER"."SIM_RAND" r) b""", {"s": self.seq, "t0": _fmt(t0), "ob": o["bank"], "ou": _fmt(o["until"])})
        cyc = pipeline_cycle_seconds()
        num = lambda expr, width: f"LPAD(CAST(CAST(FLOOR({expr}) AS DECIMAL(18,0)) AS VARCHAR(20)), {width}, '0')"
        payee = f"""CASE WHEN "TXN_TYPE" = 'P2M' THEN 'MERCH' || {num('R10 * ' + str(GEN['ids']['merchants']), 6)}
                         ELSE 'P' || {num('R10 * ' + str(GEN['ids']['customers']), 7)} END"""
        C.execute(f"""CREATE OR REPLACE TABLE "VERIFIER"."SIM_BATCH" AS
SELECT x.*,
  CASE "OUTCOME" WHEN 'NARRATION_ONLY' THEN CASE MOD(i, 4)
         WHEN 0 THEN 'UPI-' || "PAYEE" || ' ' || "MOB" || ' REF NO ' || "RRN" || ' ' || "D"
         WHEN 1 THEN "D" || ' UPI*' || "BANK" || '*' || "PAYEE" || '*RRN:' || "RRN" || '*M' || "MOB"
         WHEN 2 THEN 'TO ' || "PAYEE" || ' VIA UPI ' || "MOB" || '/' || "RRN" || '/' || "BANK"
         ELSE 'upi pmt ' || "PAYEE" || ' ref' || "RRN" || ' dt' || "D" END
       WHEN 'NARRATION_NOREF' THEN CASE MOD(i, 2) WHEN 0 THEN 'UPI PAYMENT TO ' || "PAYEE" || ' ' || "BANK" || ' ' || "D"
                                                  ELSE 'UPI TRF ' || "PAYEE" || ' ' || "BANK" END
       ELSE CASE MOD(i, 2) WHEN 0 THEN 'UPI/DR/' || "RRN" || '/' || "PAYEE" || '/' || "BANK"
                           ELSE 'UPI/DR/' || "RRN" || '/' || "PAYEE" || '/' || "BANK" || '/' || "UPI_TXN_ID" END END AS "NARRATION"
FROM (SELECT s.*, {payee} AS "PAYEE", '9' || {num('R11 * 1000000000', 9)} AS "MOB", TO_CHAR("TXN_TS", 'DDMMYYYY') AS "D",
        'XXXXXXXX' || {num('R12 * 10000', 4)} AS "ACCT",
        CASE "OUTCOME" WHEN 'BUSINESS_DECLINE' THEN 'FAILED'
             WHEN 'DEBIT_NO_CREDIT' THEN CASE WHEN R13 < 0.5 THEN 'FAILED' WHEN R13 < 0.8 THEN 'TIMEOUT' ELSE 'PENDING' END
             ELSE 'SUCCESS' END AS "SW_STATUS",
        CASE "OUTCOME" WHEN 'BUSINESS_DECLINE' THEN 'BD0' || CAST(MOD(i, 4) + 1 AS VARCHAR(1))
             WHEN 'DEBIT_NO_CREDIT' THEN 'TD0' || CAST(MOD(i, 3) + 1 AS VARCHAR(1)) ELSE '00' END AS "RESP_CODE",
        CASE WHEN "OUTCOME" IN ('BUSINESS_DECLINE', 'DEBIT_NO_CREDIT') THEN 'FAILED' ELSE 'SUCCESS' END AS "NPCI_STATUS",
        CASE WHEN "OUTCOME" = 'AMOUNT_MISMATCH' THEN "AMOUNT_PAISE" + CASE MOD(i, 4) WHEN 0 THEN 100 WHEN 1 THEN 1 WHEN 2 THEN 1000 ELSE 50 END
             ELSE "AMOUNT_PAISE" END AS "CBS_AMOUNT",
        ADD_SECONDS("TXN_TS", 5 + FLOOR(R14 * {int(GEN['timing']['cbs_post_lag_s']) - 5})) AS "POST_TS",
        CASE WHEN R15 < 0.55 THEN 'APP' WHEN R15 < 0.60 THEN 'WEB' WHEN R15 < 0.85 THEN 'QR' ELSE 'INTENT' END AS "CHANNEL",
        CAST("TXN_TS" AS DATE) AS "SETTLEMENT_DT", FLOOR(HOUR("TXN_TS") * 3600 / {cyc}) + 1 AS "CYCLE_NO",
        CASE WHEN "OUTCOME" = 'DEBIT_NO_CREDIT' THEN CASE WHEN "TXN_TYPE" = 'P2P' THEN {reversal_case('P2P', 'R16')}
                                                          ELSE {reversal_case('P2M', 'R16')} END END AS "REV_LAG"
      FROM "VERIFIER"."SIM_BASE" s) x
WHERE NOT EXISTS (SELECT 1 FROM "RAW"."SWITCH_LOG" w WHERE w."RRN" = x."RRN")""")
        b = '"VERIFIER"."SIM_BATCH"'
        t = {}
        t["switch"] = self._insert(C, f"""INSERT INTO "RAW"."SWITCH_LOG" SELECT CASE WHEN "OUTCOME" = 'SWITCH_ID_MISSING' THEN NULL ELSE "UPI_TXN_ID" END,
            "RRN", "TXN_TS", "AMOUNT_PAISE", "SW_STATUS", "RESP_CODE", "CHANNEL" FROM {b}""", "UPI switch logged the bank's payments")
        self._insert(C, f"""INSERT INTO "RAW"."CBS_LEDGER" SELECT 'D' || "UPI_TXN_ID", "ACCT", "POST_TS", 'DR', "CBS_AMOUNT", "NARRATION"
            FROM {b} WHERE "OUTCOME" NOT IN ('BUSINESS_DECLINE', 'NPCI_SUCCESS_NO_CBS')
            UNION ALL SELECT 'E' || "UPI_TXN_ID", "ACCT", ADD_SECONDS("POST_TS", {int(GEN['timing']['duplicate_extra_lag_s'])}), 'DR', "CBS_AMOUNT", "NARRATION"
            FROM {b} WHERE "OUTCOME" = 'DUPLICATE_POSTING'""", "Core banking posted the debits")
        C.execute(f"""INSERT INTO "VERIFIER"."SIM_NPCI_PENDING" SELECT "UPI_TXN_ID", "RRN", ADD_SECONDS("TXN_TS", FLOOR(R14 * 4)), "SETTLEMENT_DT",
            "CYCLE_NO", "AMOUNT_PAISE", {{p}}, "BANK", "TXN_TYPE", "RESP_CODE", "NPCI_STATUS" FROM {b}""", {"p": GEN["ids"]["bank_code"]})
        C.execute(f"""INSERT INTO "VERIFIER"."SIM_REVERSALS" SELECT "RRN", 'R' || "UPI_TXN_ID", "ACCT",
            GREATEST(ADD_SECONDS(CAST(ADD_DAYS("SETTLEMENT_DT", "REV_LAG") AS TIMESTAMP), FLOOR(R13 * 3600)), ADD_SECONDS("POST_TS", 60)),
            "CBS_AMOUNT", 'UPI/REV/' || "RRN" || '/' || "PAYEE" || '/' || "BANK" FROM {b} WHERE "REV_LAG" IS NOT NULL""")
        C.execute(f"""INSERT INTO "VERIFIER"."SIM_TRUTH" SELECT "UPI_TXN_ID", "RRN", "TXN_TS", "SETTLEMENT_DT", "CYCLE_NO", "OUTCOME",
            CASE WHEN "OUTCOME" IN ({', '.join(f"'{x}'" for x in BREAKS)}) THEN "OUTCOME" END, "AMOUNT_PAISE", "BANK", NULL FROM {b}""")
        made = dict(C.execute(f'SELECT "OUTCOME", COUNT(*) FROM {b} GROUP BY "OUTCOME"').fetchall())
        self.seq += int(n)
        return {k: int(v) for k, v in made.items()}

    def _insert(self, C, sql, title):
        t0 = time.perf_counter()
        st = C.execute(sql)
        self.e.log("Bank", title, sql if len(sql) < 900 else sql[:900] + "\n…", round((time.perf_counter() - t0) * 1000), st.rowcount())
        return st.rowcount()

    def _reversals(self, C, t1) -> int:
        st = C.execute("""INSERT INTO "RAW"."CBS_LEDGER" SELECT r."CBS_ENTRY_ID", r."ACCOUNT_NO_MASKED", r."DUE_TS", 'CR', r."AMOUNT_PAISE", r."NARRATION"
            FROM "VERIFIER"."SIM_REVERSALS" r WHERE r."DUE_TS" <= {t}
            AND NOT EXISTS (SELECT 1 FROM "RAW"."CBS_LEDGER" c WHERE c."DR_CR" = 'CR' AND SUBSTR(c."NARRATION", 1, 21) = 'UPI/REV/' || r."RRN" || '/')""",
                       {"t": _fmt(t1)})
        n = int(st.rowcount())
        C.execute("""DELETE FROM "VERIFIER"."SIM_REVERSALS" WHERE "DUE_TS" <= {t}""", {"t": _fmt(t1)})
        if n:
            self.counts["reversals"] += n
            self.e.log("Bank", f"Payee banks auto-reversed {n} failed debit{'s' if n != 1 else ''}", rows=n)
        return n

    def _files(self, C, t1) -> list:
        due = C.execute("""SELECT f."SETTLEMENT_DT", f."CYCLE_NO", f."ARRIVE_TS", l."EXPECTED_TS" FROM "VERIFIER"."SIM_FILES" f
            JOIN "RAW"."SETTLEMENT_FILE_LOG" l ON l."SETTLEMENT_DT" = f."SETTLEMENT_DT" AND l."CYCLE_NO" = f."CYCLE_NO"
            WHERE l."ARRIVED_TS" IS NULL AND f."ARRIVE_TS" <= {t} ORDER BY f."ARRIVE_TS" """, {"t": _fmt(t1)}).fetchall()
        done = []
        for d, c, arrive, expected in due:
            p = {"d": str(d), "c": int(c), "a": str(arrive)[:19]}
            t0 = time.perf_counter()
            n = int(C.execute("""INSERT INTO "RAW"."NPCI_SETTLEMENT" SELECT * FROM "VERIFIER"."SIM_NPCI_PENDING"
                                 WHERE "SETTLEMENT_DT" = {d} AND "CYCLE_NO" = {c!d}""", p).rowcount())
            C.execute("""DELETE FROM "VERIFIER"."SIM_NPCI_PENDING" WHERE "SETTLEMENT_DT" = {d} AND "CYCLE_NO" = {c!d}""", p)
            C.execute("""UPDATE "RAW"."SETTLEMENT_FILE_LOG" SET "ARRIVED_TS" = {a}, "RECORD_COUNT" = "RECORD_COUNT" + {n!d}
                         WHERE "SETTLEMENT_DT" = {d} AND "CYCLE_NO" = {c!d}""", {**p, "n": n})
            late = (_ts(arrive) - _ts(expected)).total_seconds() / 3600
            self.counts["files"] += 1
            self.e.log("Bank", f"NPCI settlement file for {d}, cycle {int(c)} arrived" + (f", {late:.0f} hours late" if late >= 1 else ""),
                       'INSERT INTO "RAW"."NPCI_SETTLEMENT" SELECT * FROM "VERIFIER"."SIM_NPCI_PENDING" WHERE ...',
                       round((time.perf_counter() - t0) * 1000), n, tone="warn" if late >= 1 else "")
            done.append((str(d), int(c), n))
        overdue = C.execute("""SELECT f."SETTLEMENT_DT", f."CYCLE_NO" FROM "VERIFIER"."SIM_FILES" f
            JOIN "RAW"."SETTLEMENT_FILE_LOG" l ON l."SETTLEMENT_DT" = f."SETTLEMENT_DT" AND l."CYCLE_NO" = f."CYCLE_NO"
            WHERE l."ARRIVED_TS" IS NULL AND l."EXPECTED_TS" <= {t}""", {"t": _fmt(t1)}).fetchall()
        for d, c in overdue:
            if (str(d), int(c)) not in self.late_noted:
                self.late_noted.add((str(d), int(c)))
                self.e.log("Bank", f"The NPCI file for {d}, cycle {int(c)} is overdue: its payments cannot be confirmed yet", tone="warn")
        return done

    def after_recon(self, C, t1: dt.datetime) -> dict:
        """Stamp each break the reconciliation found for the first time with the bank time it was found."""
        C.execute("""UPDATE "VERIFIER"."SIM_TRUTH" s SET "FIRST_SEEN_AS_OF" = {t}
            WHERE s."FIRST_SEEN_AS_OF" IS NULL AND s."TRUE_CLASS" IS NOT NULL
            AND EXISTS (SELECT 1 FROM "RECON"."EXCEPTIONS" e WHERE e."RRN" = s."RRN" AND e."CLASS" = s."TRUE_CLASS")""", {"t": _fmt(t1)})
        found = dict(C.execute("""SELECT "TRUE_CLASS", COUNT(*) FROM "VERIFIER"."SIM_TRUTH" WHERE "FIRST_SEEN_AS_OF" = {t}
                                  GROUP BY "TRUE_CLASS" """, {"t": _fmt(t1)}).fetchall())
        self.counts["ticks"] += 1
        self.stats_cache = None
        return {k: int(v) for k, v in found.items()}

    # ------------------------------------------------------------------ what the page shows
    def public(self) -> dict:
        o = self.outage or ({"bank": self.outage_req, "until": None} if self.outage_req else None)
        return {"running": self.running, "speed": self.speed, "speeds": [{"value": k, "label": v} for k, v in SPEEDS.items()],
                "outage": {"bank": o["bank"], "until": _fmt(o["until"]) if o["until"] else None} if o else None,
                "delay_pending": self.delay_req, "note": self.note, "counts": dict(self.counts)}

    def stats(self) -> dict | None:
        """Totals for the page, from VERIFIER (the matcher never reads it). Cached for a few seconds: many people poll."""
        if self.stats_cache is not None and time.time() - self.stats_at < 3:
            return self.stats_cache

        def go(C):
            tot = C.execute("""SELECT COUNT(*), SUM(CASE WHEN "TRUE_CLASS" IS NOT NULL THEN 1 ELSE 0 END),
                SUM(CASE WHEN "FIRST_SEEN_AS_OF" IS NOT NULL THEN 1 ELSE 0 END),
                MEDIAN(CASE WHEN "FIRST_SEEN_AS_OF" IS NOT NULL THEN MINUTES_BETWEEN("FIRST_SEEN_AS_OF", "TXN_TS") END),
                MAX(CASE WHEN "FIRST_SEEN_AS_OF" IS NOT NULL THEN MINUTES_BETWEEN("FIRST_SEEN_AS_OF", "TXN_TS") END),
                SUM(CASE WHEN "OUTCOME" = 'BUSINESS_DECLINE' THEN 1 ELSE 0 END), MIN("TXN_TS")
                FROM "VERIFIER"."SIM_TRUTH" """).fetchone()
            if not tot[0]:
                return None
            by = C.execute("""SELECT "TRUE_CLASS", COUNT(*), SUM(CASE WHEN "FIRST_SEEN_AS_OF" IS NOT NULL THEN 1 ELSE 0 END)
                FROM "VERIFIER"."SIM_TRUTH" WHERE "TRUE_CLASS" IS NOT NULL GROUP BY "TRUE_CLASS" ORDER BY 2 DESC""").fetchall()
            recent = C.execute("""SELECT e."EXC_ID", s."TRUE_CLASS", s."AMOUNT_PAISE", s."BANK", s."TXN_TS", s."FIRST_SEEN_AS_OF", w."TAT_STATE"
                FROM "VERIFIER"."SIM_TRUTH" s JOIN "RECON"."EXCEPTIONS" e ON e."RRN" = s."RRN"
                LEFT JOIN "RECON"."WORK_QUEUE" w ON w."EXC_ID" = e."EXC_ID"
                WHERE s."FIRST_SEEN_AS_OF" IS NOT NULL ORDER BY s."FIRST_SEEN_AS_OF" DESC, s."TXN_TS" DESC LIMIT 8""")
            cols = recent.column_names()
            return {"payments": int(tot[0]), "injected": int(tot[1] or 0), "caught": int(tot[2] or 0),
                    "median_minutes": None if tot[3] is None else round(float(tot[3])), "max_minutes": None if tot[4] is None else round(float(tot[4])),
                    "declined": int(tot[5] or 0), "since": str(tot[6])[:19],
                    "by_class": [{"class": c, "injected": int(n), "caught": int(k or 0)} for c, n, k in by],
                    "recent": [dict(zip(cols, [None if v is None else str(v) for v in r])) for r in recent]}
        try:
            self.stats_cache = self.e.fast.run(go)
        except Exception:      # the tables appear on the first tick or the next reset
            self.stats_cache = None
        self.stats_at = time.time()
        return self.stats_cache


def pipeline_cycle_seconds() -> int:
    return 86400 // int(GEN["settlement"]["cycles_per_day"])


# Accuracy for the simulated traffic: what the reconciliation should say right now, given what has arrived. Before its
# NPCI file arrives a payment cannot be confirmed, so no break is expected yet; a duplicate debit shows without NPCI; once
# the file is overdue every payment that moved money waits as LATE_FILE (sql/15_classify.sql, in the same order).
SIM_CONFUSION_SQL = """WITH a AS (SELECT CAST("PARAM_VALUE" AS TIMESTAMP) AS "AS_OF" FROM "RECON"."SETTINGS" WHERE "PARAM_NAME" = 'as_of'),
x AS (SELECT s."RRN", s."UPI_TXN_ID", s."OUTCOME", l."ARRIVED_TS",
             CASE WHEN l."ARRIVED_TS" IS NOT NULL THEN s."TRUE_CLASS"
                  WHEN s."TRUE_CLASS" = 'DUPLICATE_POSTING' THEN s."TRUE_CLASS"
                  WHEN l."EXPECTED_TS" <= a."AS_OF" AND s."OUTCOME" <> 'BUSINESS_DECLINE' THEN 'LATE_FILE' END AS "EXPECTED_CLASS"
      FROM "VERIFIER"."SIM_TRUTH" s CROSS JOIN a
      LEFT JOIN "RAW"."SETTLEMENT_FILE_LOG" l ON l."SETTLEMENT_DT" = s."SETTLEMENT_DT" AND l."CYCLE_NO" = s."CYCLE_NO"),
o AS (SELECT "CBS_ENTRY_ID", "CLASS" FROM "RECON"."EXCEPTIONS" WHERE "CLASS" = 'UNMATCHED_CBS_DEBIT'),
p AS (SELECT x."EXPECTED_CLASS" AS "EXP", e."CLASS" AS "ACT"
      FROM x LEFT JOIN "RECON"."EXCEPTIONS" e ON e."RRN" = x."RRN" AND e."CLASS" <> 'UNMATCHED_CBS_DEBIT'
      UNION ALL   -- a debit whose note has no reference cannot be tied to its payment until NPCI names the payee bank
      SELECT CASE WHEN x."OUTCOME" = 'NARRATION_NOREF' AND x."ARRIVED_TS" IS NULL THEN 'UNMATCHED_CBS_DEBIT' END, o."CLASS"
      FROM x JOIN o ON o."CBS_ENTRY_ID" = 'D' || x."UPI_TXN_ID")
SELECT COALESCE("EXP", "ACT") AS "CLS",
       SUM(CASE WHEN "EXP" = "ACT" THEN 1 ELSE 0 END) AS "TP",
       SUM(CASE WHEN "ACT" IS NOT NULL AND ("EXP" IS NULL OR "EXP" <> "ACT") THEN 1 ELSE 0 END) AS "FP",
       SUM(CASE WHEN "EXP" IS NOT NULL AND ("ACT" IS NULL OR "EXP" <> "ACT") THEN 1 ELSE 0 END) AS "FN"
FROM p GROUP BY COALESCE("EXP", "ACT")"""
