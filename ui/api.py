"""Read queries behind the TAT Guard UI. Every figure the page shows is computed here, in SQL, from live tables.

All functions take q(sql, params) -> {"columns", "rows", "ms"} (the read-only connection in ui/server.py) and
validate every user-supplied value against a whitelist or a strict pattern before it reaches SQL; values are then
passed through pyexasol's formatter, never pasted into SQL text.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import os
import pathlib
import re

import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.actions import ANALYST_PREFIX, MAKER_CHECKER, PROPOSE_WHEN, STATUSES  # noqa: E402
from recon.pipeline import LOADS  # noqa: E402

REPORTS = ROOT / "reports"
_CFG = yaml.safe_load(open(ROOT / "recon" / "config.yaml", encoding="utf-8"))
RC, UI = _CFG["rootcause"], _CFG["ui"]

TAT_STATES = ("OVERDUE", "AT_RISK", "WITHIN_TAT", "COMPENSATION_DUE", "NO_TAT_CLOCK")   # display order; see 30_penalty_view.sql
CLASS_RE = re.compile(r"^[A-Z_]{1,40}$")
BANK_RE = re.compile(r"^[A-Za-z0-9_ .&-]{1,20}$")
# Named queue views that cut across TAT states. "accruing" = the cases that add cost tomorrow.
QUEUE_FOCUS = {"accruing": 'w."NEW_ACCRUAL_24H_PAISE" > 0'}
SEARCH_RE = re.compile(r"^[A-Za-z0-9]{1,40}$")
REPORT_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,120}\.(md|csv)$")
QUEUE_SORT = {"rank": '"QUEUE_RANK"', "owed": '"EXPOSURE_NEXT_24H_PAISE"', "amount": '"AMOUNT_PAISE"',
              "time": '"TXN_TS"', "deadline": '"DEADLINE_DT"'}
PAGE_SIZES = (10, 25, 50, 100)
DEFAULT_PAGE_SIZE = 25
RS = 'CAST({} / 100 AS DECIMAL(18,2))'     # paise -> rupees, in SQL
# the action a work-queue row can be proposed for, by the same predicates agent/actions.py checks on propose
PROPOSE_ACTION_SQL = ("CASE " + " ".join(f"WHEN {cond} THEN '{a}'" for a, cond in PROPOSE_WHEN.items()) +
                      ' END AS "PROPOSE_ACTION"')


def vocabulary() -> dict:
    """The allowed values the page builds its tabs, filters and menus from (no database needed)."""
    return {"tat_states": list(TAT_STATES), "queue_sorts": list(QUEUE_SORT), "page_sizes": list(PAGE_SIZES),
            "default_page_size": DEFAULT_PAGE_SIZE, "action_statuses": list(STATUSES),
            "queue_focus": list(QUEUE_FOCUS), "maker_checker": MAKER_CHECKER, "analyst_prefix": ANALYST_PREFIX}


def records(r: dict) -> list[dict]:
    return [dict(zip(r["columns"], row)) for row in r["rows"]]


def one(r: dict) -> dict:
    rec = records(r)
    return rec[0] if rec else {}


def _int(v, default, lo, hi):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------------ health / header
def health(q) -> dict:
    r = q("SELECT PARAM_VALUE AS \"VERSION\" FROM EXA_METADATA WHERE PARAM_NAME = 'databaseProductVersion'")
    dsn = os.environ.get("EXA_DSN", "")
    host = re.split(r"[/:]", dsn, maxsplit=1)[0] if dsn else ""
    return {"version": one(r).get("VERSION"), "host": host, "ms": r["ms"]}


# ------------------------------------------------------------------ dashboard
OVERVIEW_SQL = {
    "kpi": f"""SELECT
        SUM(CASE WHEN "STATUS" = 'OPEN' THEN 1 ELSE 0 END) AS "OPEN_CASES",
        {RS.format('SUM(CASE WHEN "STATUS" = \'OPEN\' THEN "EXPOSURE_NEXT_24H_PAISE" ELSE 0 END)')} AS "OWED_TOMORROW_RS",
        {RS.format('SUM(CASE WHEN "STATUS" = \'OPEN\' THEN "PENALTY_PAISE" ELSE 0 END)')} AS "ACCRUED_RS",
        {RS.format('SUM(CASE WHEN "STATUS" = \'OPEN\' THEN "NEW_ACCRUAL_24H_PAISE" ELSE 0 END)')} AS "NEW_ACCRUAL_RS",
        SUM(CASE WHEN "STATUS" = 'OPEN' AND "PENALTY_DAYS" > 0 THEN 1 ELSE 0 END) AS "OVERDUE_N",
        {RS.format('SUM(CASE WHEN "STATUS" = \'OPEN\' AND "PENALTY_DAYS" > 0 THEN "PENALTY_PAISE" ELSE 0 END)')} AS "OVERDUE_RS",
        SUM(CASE WHEN "STATUS" = 'OPEN' AND "PENALTY_DAYS" = 0 AND "PENALTY_DAYS_NEXT_24H" > 0 THEN 1 ELSE 0 END) AS "AT_RISK_N",
        {RS.format('SUM(CASE WHEN "STATUS" = \'OPEN\' AND "PENALTY_DAYS" = 0 AND "PENALTY_DAYS_NEXT_24H" > 0 THEN "EXPOSURE_NEXT_24H_PAISE" ELSE 0 END)')} AS "AT_RISK_RS",
        SUM(CASE WHEN "COMP_STATUS" IN ('MISSING', 'UNDERPAID') THEN 1 ELSE 0 END) AS "COMP_DUE_N",
        {RS.format('SUM(CASE WHEN "COMP_STATUS" IN (\'MISSING\', \'UNDERPAID\') THEN "COMP_GAP_PAISE" ELSE 0 END)')} AS "COMP_DUE_RS",
        SUM(CASE WHEN "STATUS" = 'OPEN' AND "NEW_ACCRUAL_24H_PAISE" > 0 THEN 1 ELSE 0 END) AS "ACCRUING_N",
        {RS.format('SUM(CASE WHEN "STATUS" = \'OPEN\' THEN "DEBIT_TOTAL_PAISE" - "REVERSED_PAISE" ELSE 0 END)')} AS "STUCK_RS"
        FROM "RECON"."PENALTY_EXPOSURE" """,
    "volume": """SELECT (SELECT COUNT(*) FROM "RECON"."EXCEPTIONS") AS "EXCEPTIONS", COUNT(*) AS "TXNS",
        CAST(100 * (SELECT COUNT(*) FROM "RECON"."EXCEPTIONS") / NULLIF(COUNT(*), 0) AS DECIMAL(9,2)) AS "EXCEPTION_PCT",
        MIN(CAST("TXN_TS" AS DATE)) AS "FIRST_DT", MAX(CAST("TXN_TS" AS DATE)) AS "LAST_DT"
        FROM "RAW"."SWITCH_LOG" """,
    "as_of": """SELECT TO_CHAR(CAST("PARAM_VALUE" AS TIMESTAMP), 'YYYY-MM-DD HH24:MI') AS "AS_OF"
        FROM "RECON"."SETTINGS" WHERE "PARAM_NAME" = 'as_of'""",
    "last_recon": """WITH r AS (SELECT "RUN_ID", MAX("FINISHED_TS") AS "T" FROM "RECON"."RUN_LOG" WHERE "STEP" LIKE 'recon %'
                             GROUP BY "RUN_ID" ORDER BY "T" DESC LIMIT 1)
        SELECT TO_CHAR(r."T", 'YYYY-MM-DD HH24:MI') AS "FINISHED", SUM(l."DURATION_MS") AS "DURATION_MS"
        FROM r JOIN "RECON"."RUN_LOG" l ON l."RUN_ID" = r."RUN_ID" AND l."STEP" LIKE 'recon %' GROUP BY r."T\"""",
    "classes": """SELECT "CLASS", COUNT(*) AS "N", CAST(100 * COUNT(*) / SUM(COUNT(*)) OVER () AS DECIMAL(5,1)) AS "PCT"
        FROM "RECON"."EXCEPTIONS" GROUP BY "CLASS" ORDER BY "N" DESC""",
    "daily": """SELECT "TXN_DT", COUNT(*) AS "N" FROM "RECON"."EXCEPTIONS" WHERE "TXN_DT" IS NOT NULL
        GROUP BY "TXN_DT" ORDER BY "TXN_DT" """,
    "tat": """SELECT p."TXN_TYPE", p."CASE_NAME", MIN(p."TAT_DAYS") AS "TAT_DAYS", COUNT(*) AS "TOTAL",
        SUM(CASE WHEN p."STATUS" = 'OPEN' AND p."PENALTY_DAYS" > 0 THEN 1 ELSE 0 END) AS "OVERDUE",
        SUM(CASE WHEN p."STATUS" = 'OPEN' AND p."PENALTY_DAYS" = 0 AND p."PENALTY_DAYS_NEXT_24H" > 0 THEN 1 ELSE 0 END) AS "AT_RISK",
        SUM(CASE WHEN p."STATUS" = 'OPEN' AND p."PENALTY_DAYS_NEXT_24H" = 0 THEN 1 ELSE 0 END) AS "WITHIN_TAT",
        SUM(CASE WHEN p."STATUS" <> 'OPEN' THEN 1 ELSE 0 END) AS "REVERSED",
        SUM(CASE WHEN p."STATUS" <> 'OPEN' AND p."COMP_STATUS" IN ('MISSING', 'UNDERPAID') THEN 1 ELSE 0 END) AS "COMP_DUE"
        FROM "RECON"."PENALTY_EXPOSURE" p GROUP BY p."TXN_TYPE", p."CASE_NAME" ORDER BY p."TXN_TYPE" """,
    "rules": f"""SELECT "TXN_TYPE", "CASE_NAME", "TAT_DAYS", {RS.format('"PAISE_PER_DAY"')} AS "RS_PER_DAY", "FACT_ID"
        FROM "RECON"."TAT_RULES" ORDER BY "TXN_TYPE" """,
    "pending": """SELECT COUNT(*) AS "N" FROM "AUDIT"."PROPOSED_ACTIONS" WHERE "STATUS" = 'PROPOSED'""",
    # open debit-no-credit cases by whole days past TAT, one row per day count that exists (no bucket boundaries to invent)
    "ageing": f"""SELECT "PENALTY_DAYS" AS "DAYS", COUNT(*) AS "N",
        {RS.format('SUM("DEBIT_TOTAL_PAISE" - "REVERSED_PAISE")')} AS "STUCK_RS"
        FROM "RECON"."PENALTY_EXPOSURE" WHERE "STATUS" = 'OPEN' GROUP BY "PENALTY_DAYS" ORDER BY "PENALTY_DAYS\"""",
    # the beneficiary bank owns the auto-reversal of a P2P transfer [RBI-TAT-UPI-P2P], so this is the chase list
    "banks": f"""SELECT "BANK", COUNT(*) AS "N", SUM(CASE WHEN "PENALTY_DAYS" > 0 THEN 1 ELSE 0 END) AS "OVERDUE_N",
        {RS.format('SUM("DEBIT_TOTAL_PAISE" - "REVERSED_PAISE")')} AS "STUCK_RS", {RS.format('SUM("NEW_ACCRUAL_24H_PAISE")')} AS "NEW_ACCRUAL_RS"
        FROM "RECON"."PENALTY_EXPOSURE" WHERE "STATUS" = 'OPEN' GROUP BY "BANK"
        ORDER BY "NEW_ACCRUAL_RS" DESC, "N" DESC, "BANK" LIMIT {int(UI["top_banks"])}""",
    "compensation": f"""SELECT "COMP_STATUS", COUNT(*) AS "N", {RS.format('SUM("COMP_PAISE")')} AS "PAID_RS",
        {RS.format('SUM("COMP_GAP_PAISE")')} AS "GAP_RS" FROM "RECON"."PENALTY_EXPOSURE"
        GROUP BY "COMP_STATUS" ORDER BY "COMP_STATUS\"""",
    "missing_files": """WITH a AS (SELECT CAST("PARAM_VALUE" AS TIMESTAMP) AS "AS_OF" FROM "RECON"."SETTINGS" WHERE "PARAM_NAME" = 'as_of')
        SELECT f."SETTLEMENT_DT", f."CYCLE_NO", TO_CHAR(f."EXPECTED_TS", 'YYYY-MM-DD HH24:MI') AS "EXPECTED",
        (SELECT COUNT(*) FROM "RECON"."EXCEPTIONS" e WHERE e."CLASS" = 'LATE_FILE' AND e."FILE_SETTLEMENT_DT" = f."SETTLEMENT_DT"
         AND e."FILE_CYCLE_NO" = f."CYCLE_NO") AS "BREAKS"
        FROM "RAW"."SETTLEMENT_FILE_LOG" f CROSS JOIN a
        WHERE f."ARRIVED_TS" IS NULL AND f."EXPECTED_TS" <= a."AS_OF" ORDER BY f."EXPECTED_TS\"""",
}

# Day-by-day compensation liability. For day D and each DEBIT_NO_CREDIT case with T <= D:
#   penalty days = max(0, (min(D, R) - T) - TAT)      (R = reversal date; open cases keep accruing)
# ACCRUED_RS sums all cases; OPEN_RS only cases still unreversed on D. The day after the cut-off is a projection
# (PROJECTED = 1): what is owed tomorrow if nothing is reversed. Same rule as RECON.PENALTY_EXPOSURE.
TREND_SQL = f"""WITH a AS (SELECT CAST(CAST("PARAM_VALUE" AS TIMESTAMP) AS DATE) AS "AS_OF_DT" FROM "RECON"."SETTINGS"
                     WHERE "PARAM_NAME" = 'as_of'),
cal AS (SELECT DISTINCT "SETTLEMENT_DT" AS "D" FROM "RAW"."SETTLEMENT_FILE_LOG"
        UNION SELECT "AS_OF_DT" FROM a
        UNION SELECT ADD_DAYS("AS_OF_DT", 1) FROM a),
c AS (SELECT "TXN_DT", "REVERSAL_DT", "TAT_DAYS", "PAISE_PER_DAY" FROM "RECON"."PENALTY_EXPOSURE")
SELECT cal."D", CASE WHEN cal."D" > a."AS_OF_DT" THEN 1 ELSE 0 END AS "PROJECTED",
  {RS.format('SUM(CASE WHEN c."TXN_DT" <= cal."D" THEN GREATEST(0, DAYS_BETWEEN(LEAST(cal."D", COALESCE(c."REVERSAL_DT", cal."D")), c."TXN_DT") - c."TAT_DAYS") * c."PAISE_PER_DAY" ELSE 0 END)')} AS "ACCRUED_RS",
  {RS.format('SUM(CASE WHEN c."TXN_DT" <= cal."D" AND (c."REVERSAL_DT" IS NULL OR c."REVERSAL_DT" > cal."D") THEN GREATEST(0, DAYS_BETWEEN(cal."D", c."TXN_DT") - c."TAT_DAYS") * c."PAISE_PER_DAY" ELSE 0 END)')} AS "OPEN_RS",
  SUM(CASE WHEN c."TXN_DT" <= cal."D" AND (c."REVERSAL_DT" IS NULL OR c."REVERSAL_DT" > cal."D") THEN 1 ELSE 0 END) AS "OPEN_CASES"
FROM cal CROSS JOIN a CROSS JOIN c
GROUP BY cal."D", a."AS_OF_DT" ORDER BY cal."D" """

ACTIVITY_SQL = """SELECT TO_CHAR("TS", 'YYYY-MM-DD HH24:MI:SS') AS "TS", "KIND", "ACTION_TYPE", "TARGET_REF", "WHO", "ACTION_ID" FROM (
  SELECT "CREATED_TS" AS "TS", 'PROPOSED' AS "KIND", "ACTION_TYPE", "TARGET_REF", "CREATED_BY" AS "WHO", "ACTION_ID"
  FROM "AUDIT"."PROPOSED_ACTIONS"
  UNION ALL
  SELECT "DECIDED_TS", "STATUS", "ACTION_TYPE", "TARGET_REF", "DECIDED_BY", "ACTION_ID"
  FROM "AUDIT"."PROPOSED_ACTIONS" WHERE "DECIDED_TS" IS NOT NULL AND "STATUS" IN ('APPROVED', 'REJECTED')
  UNION ALL
  SELECT l."EXECUTED_TS", l."OUTCOME", p."ACTION_TYPE", p."TARGET_REF", l."EXECUTED_BY", l."ACTION_ID"
  FROM "AUDIT"."ACTION_LOG" l LEFT JOIN "AUDIT"."PROPOSED_ACTIONS" p ON p."ACTION_ID" = l."ACTION_ID")
ORDER BY 1 DESC LIMIT {n!d}"""


def overview(q) -> dict:
    out = {k: q(sql) for k, sql in OVERVIEW_SQL.items()}
    return {"kpi": one(out["kpi"]), "volume": one(out["volume"]), "as_of": one(out["as_of"]).get("AS_OF"),
            "last_recon": one(out["last_recon"]).get("FINISHED"), "recon_ms": one(out["last_recon"]).get("DURATION_MS"),
            "classes": records(out["classes"]), "ageing": records(out["ageing"]), "banks": records(out["banks"]),
            "compensation": records(out["compensation"]), "missing_files": records(out["missing_files"]),
            "daily": records(out["daily"]), "tat": records(out["tat"]), "rules": records(out["rules"]),
            "pending": one(out["pending"]).get("N"), "ms": {k: v["ms"] for k, v in out.items()}}


def trend(q) -> dict:
    r = q(TREND_SQL)
    return {"points": records(r), "ms": r["ms"]}


def activity(q, n=12) -> dict:
    r = q(ACTIVITY_SQL, {"n": _int(n, 12, 1, 100)})
    return {"items": records(r), "ms": r["ms"]}


# ------------------------------------------------------------------ work queue
QUEUE_COLS = f""""QUEUE_RANK", "EXC_ID", "UPI_TXN_ID", "RRN", "CLASS", "TXN_TYPE", "BANK",
    TO_CHAR("TXN_TS", 'YYYY-MM-DD HH24:MI') AS "TXN_TIME", "TXN_DT", "DEADLINE_DT",
    {RS.format('"AMOUNT_PAISE"')} AS "AMOUNT_RS", {RS.format('"EXPOSURE_NEXT_24H_PAISE"')} AS "OWED_TOMORROW_RS",
    {RS.format('"NEW_ACCRUAL_24H_PAISE"')} AS "NEW_ACCRUAL_RS", {RS.format('"COMP_GAP_PAISE"')} AS "COMP_GAP_RS",
    {RS.format('"PENALTY_PAISE"')} AS "ACCRUED_RS", "DAYS_TO_DEADLINE", "COMP_STATUS", "TAT_STATE", "ACTION_NEEDED", {PROPOSE_ACTION_SQL},
    (SELECT MAX(a."ACTION_ID") FROM "AUDIT"."PROPOSED_ACTIONS" a
     WHERE a."TARGET_REF" = w."EXC_ID" AND a."STATUS" = 'PROPOSED') AS "PENDING_ACTION_ID\""""


def _queue_where(cls: str, search: str, state: str | None, bank: str = "", focus: str = "") -> tuple[str, dict]:
    cond, params = [], {}
    if focus:
        if focus not in QUEUE_FOCUS:
            raise ValueError("bad queue view")
        cond.append(QUEUE_FOCUS[focus])
    if bank:
        if not BANK_RE.match(bank):
            raise ValueError("bad bank")
        cond.append('w."BANK" = {bank}')
        params["bank"] = bank
    if cls:
        if not CLASS_RE.match(cls):
            raise ValueError("bad break type")
        cond.append('w."CLASS" = {cls}')
        params["cls"] = cls
    if search:
        if not SEARCH_RE.match(search):
            raise ValueError("search accepts letters and digits only (a UPI id, RRN or exception id)")
        cond.append('(w."EXC_ID" = {s} OR w."UPI_TXN_ID" = {s} OR w."RRN" = {s} OR w."UPI_TXN_ID" LIKE {sp} OR w."RRN" LIKE {sp})')
        params.update(s=search, sp=search + "%")
    if state:
        if state not in TAT_STATES:
            raise ValueError("bad TAT state")
        cond.append('w."TAT_STATE" = {st}')
        params["st"] = state
    return ("WHERE " + " AND ".join(cond)) if cond else "", params


def queue(q, args: dict) -> dict:
    cls, search, state = args.get("class", ""), args.get("q", "").strip(), args.get("state", "")
    bank, focus = args.get("bank", ""), args.get("focus", "")
    sort_key = args.get("sort", "rank") if args.get("sort", "rank") in QUEUE_SORT else "rank"
    sort = QUEUE_SORT[sort_key]
    default_dir = "asc" if sort_key in ("rank", "deadline") else "desc"
    direction = "ASC" if args.get("dir", default_dir) == "asc" else "DESC"
    size = _int(args.get("size"), DEFAULT_PAGE_SIZE, 1, max(PAGE_SIZES))
    size = size if size in PAGE_SIZES else DEFAULT_PAGE_SIZE
    page = _int(args.get("page"), 1, 1, 10**6)
    where, params = _queue_where(cls, search, state, bank, focus)
    rows = q(f'SELECT {QUEUE_COLS} FROM "RECON"."WORK_QUEUE" w {where} '
             f'ORDER BY {sort} {direction} NULLS LAST, "QUEUE_RANK" LIMIT {{lim!d}} OFFSET {{off!d}}',
             {**params, "lim": size, "off": (page - 1) * size})
    total = one(q(f'SELECT COUNT(*) AS "N" FROM "RECON"."WORK_QUEUE" w {where}', params))["N"]
    where_tabs, ptabs = _queue_where(cls, search, None, bank)
    tabs = q(f'SELECT w."TAT_STATE", COUNT(*) AS "N", SUM(CASE WHEN w."NEW_ACCRUAL_24H_PAISE" > 0 THEN 1 ELSE 0 END) AS "ACCRUING" '
             f'FROM "RECON"."WORK_QUEUE" w {where_tabs} GROUP BY w."TAT_STATE"', ptabs)
    classes = q('SELECT DISTINCT "CLASS" FROM "RECON"."WORK_QUEUE" ORDER BY 1')
    tab_rows = records(tabs)
    return {"rows": records(rows), "total": total, "page": page, "size": size, "ms": rows["ms"],
            "tabs": {r["TAT_STATE"]: r["N"] for r in tab_rows}, "accruing": sum(int(r["ACCRUING"]) for r in tab_rows),
            "classes": [c["CLASS"] for c in records(classes)]}


def queue_csv(q, args: dict) -> str:
    cls, search, state = args.get("class", ""), args.get("q", "").strip(), args.get("state", "")
    where, params = _queue_where(cls, search, state, args.get("bank", ""), args.get("focus", ""))
    return _csv(q(f'SELECT {QUEUE_COLS} FROM "RECON"."WORK_QUEUE" w {where} ORDER BY "QUEUE_RANK"', params))


def _csv(r: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(r["columns"])
    w.writerows(r["rows"])
    return buf.getvalue()


# Evidence that suo-moto compensation was paid: every case that went past TAT, whether or not a customer complained.
COMPENSATION_CSV_SQL = f"""SELECT "EXC_ID", "UPI_TXN_ID", "RRN", "TXN_TYPE", "BANK", "TXN_DT", "DEADLINE_DT", "STATUS", "REVERSAL_DT",
    "PENALTY_DAYS", {RS.format('"PENALTY_PAISE"')} AS "OWED_RS", {RS.format('"COMP_PAISE"')} AS "PAID_RS",
    {RS.format('"COMP_GAP_PAISE"')} AS "GAP_RS", "COMP_STATUS", "AS_OF_DT"
    FROM "RECON"."PENALTY_EXPOSURE" WHERE "PENALTY_DAYS" > 0 ORDER BY "TXN_DT", "EXC_ID\""""


def compensation_csv(q) -> str:
    return _csv(q(COMPENSATION_CSV_SQL))


# ------------------------------------------------------------------ transactions
# Exception ids are 'E' || COALESCE(UPI_TXN_ID, 'RRN' || RRN) (sql/15_classify.sql), so one equality join finds a
# transaction's exception; an OR join here would force a nested loop over every transaction.
TXN_LIST_SQL = f"""SELECT TO_CHAR(t."SW_TS", 'YYYY-MM-DD HH24:MI:SS') AS "TXN_TIME", t."UPI_TXN_ID", t."RRN", t."TXN_TYPE",
    t."PAYEE_BANK", {RS.format('t."AMOUNT_PAISE"')} AS "AMOUNT_RS", t."SW_STATUS", t."NPCI_STATUS", t."DR_CNT",
    e."CLASS", e."EXC_ID"
    FROM "RECON"."TXN_STATE" t LEFT JOIN "RECON"."EXCEPTIONS" e
      ON e."EXC_ID" = 'E' || COALESCE(t."UPI_TXN_ID", 'RRN' || t."RRN")
    {{where}} ORDER BY t."SW_TS" DESC, t."RRN" LIMIT {{lim!d}} OFFSET {{off!d}}"""


def transactions(q, args: dict) -> dict:
    search, outcome = args.get("q", "").strip(), args.get("outcome", "")
    size = _int(args.get("size"), DEFAULT_PAGE_SIZE, 1, max(PAGE_SIZES))
    size = size if size in PAGE_SIZES else DEFAULT_PAGE_SIZE
    page = _int(args.get("page"), 1, 1, 10**6)
    cond, params = [], {"lim": size, "off": (page - 1) * size}
    if search:
        if not SEARCH_RE.match(search):
            raise ValueError("search accepts letters and digits only (a UPI id or RRN)")
        cond.append('(t."UPI_TXN_ID" = {s} OR t."RRN" = {s} OR t."UPI_TXN_ID" LIKE {sp} OR t."RRN" LIKE {sp})')
        params.update(s=search, sp=search + "%")
    if outcome == "exception":
        cond.append('e."EXC_ID" IS NOT NULL')
    elif outcome == "clean":
        cond.append('e."EXC_ID" IS NULL')
    elif outcome:
        raise ValueError("bad outcome filter")
    where = ("WHERE " + " AND ".join(cond)) if cond else ""
    rows = q(TXN_LIST_SQL.replace("{where}", where), params)
    total = one(q(f"""SELECT COUNT(*) AS "N" FROM "RECON"."TXN_STATE" t LEFT JOIN "RECON"."EXCEPTIONS" e
      ON e."EXC_ID" = 'E' || COALESCE(t."UPI_TXN_ID", 'RRN' || t."RRN") {where}""",
                  {k: v for k, v in params.items() if k in ("s", "sp")}))["N"]
    return {"rows": records(rows), "total": total, "page": page, "size": size, "ms": rows["ms"]}


def transaction_detail(q, ref: str) -> dict:
    """Everything the three sources and the recon say about one transaction (by UPI id, RRN or exception id)."""
    ref = ref.strip()
    if not SEARCH_RE.match(ref):
        raise ValueError("an id has letters and digits only")
    exc = one(q("""SELECT "EXC_ID", "UPI_TXN_ID", "RRN", "CBS_ENTRY_ID", "CLASS", "STATUS", "TXN_DT",
                   TO_CHAR("TXN_TS", 'YYYY-MM-DD HH24:MI:SS') AS "TXN_TIME", "TXN_TYPE", "BANK",
                   CAST("AMOUNT_PAISE" / 100 AS DECIMAL(18,2)) AS "AMOUNT_RS",
                   CAST("DEBIT_AMOUNT_PAISE" / 100 AS DECIMAL(18,2)) AS "DEBIT_AMOUNT_RS", "DR_CNT", "REVERSAL_DT",
                   CAST("DEBIT_TOTAL_PAISE" / 100 AS DECIMAL(18,2)) AS "DEBIT_TOTAL_RS",
                   CAST("REVERSED_PAISE" / 100 AS DECIMAL(18,2)) AS "REVERSED_RS",
                   CAST("COMP_PAISE" / 100 AS DECIMAL(18,2)) AS "COMP_RS", "FILE_SETTLEMENT_DT", "FILE_CYCLE_NO",
                   "RESP_CODE", "MATCH_PASS", "CBS_PASS"
                   FROM "RECON"."EXCEPTIONS" WHERE "EXC_ID" = {r} OR "UPI_TXN_ID" = {r} OR "RRN" = {r} LIMIT 1""",
                {"r": ref}))
    uid = exc.get("UPI_TXN_ID") or ref
    rrn = exc.get("RRN") or ref
    state = one(q("""SELECT "UPI_TXN_ID", "RRN", TO_CHAR("SW_TS", 'YYYY-MM-DD HH24:MI:SS') AS "TXN_TIME", "TXN_TYPE",
                     "PAYEE_BANK", CAST("AMOUNT_PAISE" / 100 AS DECIMAL(18,2)) AS "AMOUNT_RS", "SW_STATUS", "SW_RESP",
                     "NPCI_STATUS", "NPCI_RESP", "MATCH_PASS", "DR_CNT", "REV_CNT", "REVERSAL_DT",
                     CAST("COMP_PAISE" / 100 AS DECIMAL(18,2)) AS "COMP_RS", "CBS_PASS",
                     "FILE_SETTLEMENT_DT", "FILE_CYCLE_NO", TO_CHAR("FILE_EXPECTED_TS", 'YYYY-MM-DD HH24:MI') AS "FILE_EXPECTED",
                     TO_CHAR("FILE_ARRIVED_TS", 'YYYY-MM-DD HH24:MI') AS "FILE_ARRIVED"
                     FROM "RECON"."TXN_STATE" WHERE "UPI_TXN_ID" = {u} OR "RRN" = {r} LIMIT 1""", {"u": uid, "r": rrn}))
    if not exc and not state:
        raise ValueError(f"no transaction or exception matches {ref}")
    rrn = state.get("RRN") or rrn
    uid = state.get("UPI_TXN_ID") or exc.get("UPI_TXN_ID") or uid
    switch = q("""SELECT TO_CHAR("TXN_TS", 'YYYY-MM-DD HH24:MI:SS') AS "TXN_TIME", "UPI_TXN_ID", "RRN",
                  CAST("AMOUNT_PAISE" / 100 AS DECIMAL(18,2)) AS "AMOUNT_RS", "STATUS", "RESP_CODE", "CHANNEL"
                  FROM "RAW"."SWITCH_LOG" WHERE "RRN" = {r} ORDER BY "TXN_TS" """, {"r": rrn})
    npci = q("""SELECT TO_CHAR("TXN_TS", 'YYYY-MM-DD HH24:MI:SS') AS "TXN_TIME", "UPI_TXN_ID", "SETTLEMENT_DT", "CYCLE_NO",
                CAST("AMOUNT_PAISE" / 100 AS DECIMAL(18,2)) AS "AMOUNT_RS", "PAYEE_BANK", "TXN_TYPE", "STATUS", "RESP_CODE"
                FROM "RAW"."NPCI_SETTLEMENT" WHERE "UPI_TXN_ID" = {u} OR "RRN" = {r}""", {"u": uid, "r": rrn})
    cbs = q("""SELECT TO_CHAR(c."POST_TS", 'YYYY-MM-DD HH24:MI:SS') AS "POST_TIME", c."CBS_ENTRY_ID", c."DR_CR",
               CAST(c."AMOUNT_PAISE" / 100 AS DECIMAL(18,2)) AS "AMOUNT_RS", m."KIND", m."MATCH_PASS", c."NARRATION"
               FROM "RAW"."CBS_LEDGER" c JOIN "RECON"."CBS_MATCH" m ON m."CBS_ENTRY_ID" = c."CBS_ENTRY_ID"
               WHERE m."RRN" = {r}
               UNION ALL
               SELECT TO_CHAR(c."POST_TS", 'YYYY-MM-DD HH24:MI:SS'), c."CBS_ENTRY_ID", c."DR_CR",
               CAST(c."AMOUNT_PAISE" / 100 AS DECIMAL(18,2)), 'UNMATCHED', CAST(NULL AS DECIMAL(1,0)), c."NARRATION"
               FROM "RAW"."CBS_LEDGER" c WHERE c."CBS_ENTRY_ID" = {e}
               ORDER BY 1""", {"r": rrn, "e": exc.get("CBS_ENTRY_ID") or "-"})
    penalty = one(q("""SELECT "CASE_NAME", "TAT_DAYS", "DEADLINE_DT", "END_DT", "PENALTY_DAYS", "DAYS_TO_DEADLINE",
                       CAST("NEW_ACCRUAL_24H_PAISE" / 100 AS DECIMAL(18,2)) AS "NEW_ACCRUAL_RS",
                       CAST("PENALTY_PAISE" / 100 AS DECIMAL(18,2)) AS "PENALTY_RS",
                       CAST("EXPOSURE_NEXT_24H_PAISE" / 100 AS DECIMAL(18,2)) AS "OWED_TOMORROW_RS",
                       "COMP_STATUS", CAST("COMP_GAP_PAISE" / 100 AS DECIMAL(18,2)) AS "COMP_GAP_RS"
                       FROM "RECON"."PENALTY_EXPOSURE" WHERE "EXC_ID" = {e}""", {"e": exc.get("EXC_ID") or "-"}))
    queue_row = one(q(f'SELECT "QUEUE_RANK", "TAT_STATE", "ACTION_NEEDED", {PROPOSE_ACTION_SQL} '
                      'FROM "RECON"."WORK_QUEUE" WHERE "EXC_ID" = {e}', {"e": exc.get("EXC_ID") or "-"}))
    actions = q("""SELECT "ACTION_ID", "ACTION_TYPE", "STATUS", "CREATED_BY", TO_CHAR("CREATED_TS", 'YYYY-MM-DD HH24:MI') AS "CREATED",
                   "DECIDED_BY", TO_CHAR("DECIDED_TS", 'YYYY-MM-DD HH24:MI') AS "DECIDED"
                   FROM "AUDIT"."PROPOSED_ACTIONS" WHERE "TARGET_REF" = {e} ORDER BY "CREATED_TS" DESC""",
                {"e": exc.get("EXC_ID") or "-"})
    return {"exception": exc or None, "state": state or None, "switch": records(switch), "npci": records(npci),
            "cbs": records(cbs), "penalty": penalty or None, "queue": queue_row or None, "actions": records(actions)}


# ------------------------------------------------------------------ actions / audit
def proposals(q, status: str = "") -> dict:
    if status and status not in STATUSES:
        raise ValueError("bad status")
    r = q("""SELECT p."ACTION_ID", TO_CHAR(p."CREATED_TS", 'YYYY-MM-DD HH24:MI:SS') AS "CREATED", p."CREATED_BY",
             p."ACTION_TYPE", p."TARGET_REF", p."RATIONALE", p."STATUS", p."DECIDED_BY",
             TO_CHAR(p."DECIDED_TS", 'YYYY-MM-DD HH24:MI:SS') AS "DECIDED", w."TAT_STATE",
             CAST(w."NEW_ACCRUAL_24H_PAISE" / 100 AS DECIMAL(18,2)) AS "NEW_ACCRUAL_RS",
             CAST(CASE p."ACTION_TYPE" WHEN 'POST_REVERSAL' THEN e."DEBIT_TOTAL_PAISE" - e."REVERSED_PAISE"
                                       WHEN 'PAY_COMPENSATION' THEN w."COMP_GAP_PAISE" END / 100 AS DECIMAL(18,2)) AS "POST_RS"
             FROM "AUDIT"."PROPOSED_ACTIONS" p
             LEFT JOIN "RECON"."WORK_QUEUE" w ON w."EXC_ID" = p."TARGET_REF"
             LEFT JOIN "RECON"."EXCEPTIONS" e ON e."EXC_ID" = p."TARGET_REF" """ + ("WHERE p.\"STATUS\" = {st} " if status else "") +
          """ORDER BY CASE WHEN p."STATUS" = 'PROPOSED' THEN 0 ELSE 1 END, p."CREATED_TS" DESC LIMIT 200""", {"st": status})
    counts = q("""SELECT "STATUS", COUNT(*) AS "N" FROM "AUDIT"."PROPOSED_ACTIONS" GROUP BY "STATUS" """)
    return {"rows": records(r), "counts": {c["STATUS"]: c["N"] for c in records(counts)}, "ms": r["ms"]}


def audit_log(q) -> dict:
    r = q("""SELECT TO_CHAR(l."EXECUTED_TS", 'YYYY-MM-DD HH24:MI:SS') AS "EXECUTED", l."LOG_ID", l."ACTION_ID", p."ACTION_TYPE",
             p."TARGET_REF", p."CREATED_BY", l."EXECUTED_BY", l."OUTCOME", l."EXECUTED_SQL", l."BEFORE_JSON", l."AFTER_JSON"
             FROM "AUDIT"."ACTION_LOG" l LEFT JOIN "AUDIT"."PROPOSED_ACTIONS" p ON p."ACTION_ID" = l."ACTION_ID"
             ORDER BY l."EXECUTED_TS" DESC LIMIT 200""")
    return {"rows": records(r), "ms": r["ms"]}


# ------------------------------------------------------------------ data sources / reports
def sources(q) -> dict:
    # one count per table the pipeline loads (recon/pipeline.py LOADS: fixed names, not user input)
    tbls = [t.split(".") for _, t in LOADS]
    counts = q(" UNION ALL ".join(f"""SELECT '{n}' AS "TBL", COUNT(*) AS "N" FROM "{s}"."{n}\"""" for s, n in tbls))
    cols = q("""SELECT COLUMN_TABLE AS "TBL", COUNT(*) AS "COLS" FROM EXA_ALL_COLUMNS WHERE COLUMN_SCHEMA = 'RAW'
                GROUP BY COLUMN_TABLE""")
    loads = q("""WITH l AS (SELECT SUBSTR("STEP", 10) AS "TBL", "FINISHED_TS", "DURATION_MS",
                               ROW_NUMBER() OVER (PARTITION BY "STEP" ORDER BY "FINISHED_TS" DESC) AS "RN"
                               FROM "RECON"."RUN_LOG" WHERE "STEP" LIKE 'load RAW.%')
                 SELECT "TBL", TO_CHAR("FINISHED_TS", 'YYYY-MM-DD HH24:MI') AS "LOADED", "DURATION_MS" FROM l WHERE "RN" = 1""")
    files = q(f"""WITH a AS (SELECT CAST("PARAM_VALUE" AS TIMESTAMP) AS "AS_OF" FROM "RECON"."SETTINGS" WHERE "PARAM_NAME" = 'as_of')
                 SELECT f."SETTLEMENT_DT", f."CYCLE_NO", TO_CHAR(f."EXPECTED_TS", 'YYYY-MM-DD HH24:MI') AS "EXPECTED",
                 TO_CHAR(f."ARRIVED_TS", 'YYYY-MM-DD HH24:MI') AS "ARRIVED", f."RECORD_COUNT",
                 CASE WHEN f."ARRIVED_TS" IS NULL AND f."EXPECTED_TS" > a."AS_OF" THEN 'NOT_DUE'
                      WHEN f."ARRIVED_TS" IS NULL THEN 'NOT_ARRIVED'
                      WHEN MINUTES_BETWEEN(f."ARRIVED_TS", f."EXPECTED_TS") > {{grace!d}} THEN 'LATE'
                      ELSE 'ON_TIME' END AS "FILE_STATUS",
                 CAST(MINUTES_BETWEEN(COALESCE(f."ARRIVED_TS", a."AS_OF"), f."EXPECTED_TS") AS DECIMAL(18,0)) AS "MINUTES_AFTER_EXPECTED"
                 FROM "RAW"."SETTLEMENT_FILE_LOG" f CROSS JOIN a ORDER BY f."SETTLEMENT_DT", f."CYCLE_NO" """,
              {"grace": int(RC["file_grace_minutes"])})
    c = {r["TBL"]: r["COLS"] for r in records(cols)}
    l = {r["TBL"]: r for r in records(loads)}
    tables = [{"TABLE": r["TBL"], "ROWS": r["N"], "COLS": c.get(r["TBL"]), "LOADED": l.get(r["TBL"], {}).get("LOADED"),
               "LOAD_MS": l.get(r["TBL"], {}).get("DURATION_MS")} for r in records(counts)]
    return {"tables": tables, "files": records(files), "grace_minutes": int(RC["file_grace_minutes"]), "ms": counts["ms"]}


def reports_list() -> dict:
    items = []
    for p in sorted(REPORTS.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True):
        if p.is_file() and REPORT_RE.match(p.name):
            items.append({"name": p.name, "bytes": p.stat().st_size,
                          "modified": dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")})
    return {"items": items}


def report_text(name: str) -> dict:
    if not REPORT_RE.match(name):
        raise ValueError("bad report name")
    p = (REPORTS / name).resolve()
    if p.parent != REPORTS.resolve() or not p.is_file():
        raise ValueError("no such report")
    return {"name": name, "text": p.read_text(encoding="utf-8", errors="replace")}


def runs(q) -> dict:
    r = q("""SELECT "RUN_ID", TO_CHAR(MIN("STARTED_TS"), 'YYYY-MM-DD HH24:MI') AS "STARTED", COUNT(*) AS "STEPS",
             SUM(CASE WHEN "STEP" LIKE 'recon %' THEN "DURATION_MS" ELSE 0 END) AS "RECON_MS",
             SUM(CASE WHEN "STEP" LIKE 'load %' THEN "DURATION_MS" ELSE 0 END) AS "LOAD_MS",
             MAX(CASE WHEN "STEP" LIKE 'load RAW.SWITCH_LOG' THEN "ROW_COUNT" END) AS "ROWS_LOADED"
             FROM "RECON"."RUN_LOG" GROUP BY "RUN_ID" ORDER BY MIN("STARTED_TS") DESC LIMIT 30""")
    last = q("""WITH r AS (SELECT "RUN_ID", MAX("STARTED_TS") AS "T" FROM "RECON"."RUN_LOG" WHERE "STEP" LIKE 'recon %'
                           GROUP BY "RUN_ID" ORDER BY "T" DESC LIMIT 1)
                SELECT l."STEP", l."DURATION_MS" FROM "RECON"."RUN_LOG" l JOIN r ON r."RUN_ID" = l."RUN_ID"
                ORDER BY l."STARTED_TS", l."STEP" """)
    return {"runs": records(r), "last": records(last), "ms": r["ms"]}
