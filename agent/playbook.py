"""Deterministic root-cause and status playbooks (01 Phase 4: "deterministic SQL first, LLM only narrates").

Every query is a single SELECT so it can run through the MCP server's execute_exasol_query. Every number in the
generated text is read from those query results (checked by agent/grounding_guard.py); derived numbers
(baselines, percentages, rupee totals) are computed in SQL.
"""
from __future__ import annotations

import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
RC = yaml.safe_load(open(ROOT / "recon" / "config.yaml", encoding="utf-8"))["rootcause"]
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SPIKE_SQL = f"""WITH c AS (
  SELECT "TXN_DT", "FILE_CYCLE_NO" AS "CYCLE_NO", COUNT(*) AS "N"
  FROM "RECON"."EXCEPTIONS" WHERE "FILE_CYCLE_NO" IS NOT NULL
  GROUP BY "TXN_DT", "FILE_CYCLE_NO"),
w AS (
  SELECT c."TXN_DT", c."CYCLE_NO", c."N",
         CAST((SUM(c."N") OVER (PARTITION BY c."CYCLE_NO") - c."N")
              / NULLIF(COUNT(*) OVER (PARTITION BY c."CYCLE_NO") - 1, 0) AS DECIMAL(18,1)) AS "BASELINE_N"
  FROM c)
SELECT "TXN_DT", "CYCLE_NO", "N" AS "EXCEPTIONS", "BASELINE_N",
       CAST("N" / NULLIF("BASELINE_N", 0) AS DECIMAL(18,1)) AS "X_BASELINE"
FROM w ORDER BY "N" - COALESCE("BASELINE_N", 0) DESC LIMIT {int(RC["top_windows"])}"""

FILES_SQL = f"""WITH a AS (SELECT CAST("PARAM_VALUE" AS TIMESTAMP) AS "AS_OF" FROM "RECON"."SETTINGS" WHERE "PARAM_NAME" = 'as_of'),
f AS (
  SELECT l."SETTLEMENT_DT", l."CYCLE_NO", TO_CHAR(l."EXPECTED_TS", 'YYYY-MM-DD HH24:MI') AS "EXPECTED_TS",
         TO_CHAR(l."ARRIVED_TS", 'YYYY-MM-DD HH24:MI') AS "ARRIVED_TS", TO_CHAR(a."AS_OF", 'YYYY-MM-DD HH24:MI') AS "AS_OF",
         CASE WHEN l."ARRIVED_TS" IS NULL THEN 'NOT_ARRIVED' ELSE 'ARRIVED_LATE' END AS "FILE_STATUS",
         CAST(MINUTES_BETWEEN(COALESCE(l."ARRIVED_TS", a."AS_OF"), l."EXPECTED_TS") AS DECIMAL(18,0)) AS "MINUTES_LATE"
  FROM "RAW"."SETTLEMENT_FILE_LOG" l CROSS JOIN a
  WHERE l."EXPECTED_TS" <= a."AS_OF")
SELECT * FROM f WHERE "MINUTES_LATE" > {int(RC["file_grace_minutes"])} ORDER BY "MINUTES_LATE" DESC LIMIT 10"""

TD_SQL = """WITH d AS (
  SELECT CAST(s."TXN_TS" AS DATE) AS "TXN_DT", COUNT(*) AS "TXNS",
         SUM(CASE WHEN m."CATEGORY" = 'TECHNICAL_DECLINE' THEN 1 ELSE 0 END) AS "TD"
  FROM "RAW"."SWITCH_LOG" s LEFT JOIN "RECON"."RESP_CODE_MAP" m ON m."RESP_CODE" = s."RESP_CODE"
  GROUP BY CAST(s."TXN_TS" AS DATE))
SELECT "TXN_DT", "TXNS", "TD", CAST(100 * "TD" / "TXNS" AS DECIMAL(9,3)) AS "TD_PCT",
       CAST(100 * (SUM("TD") OVER () - "TD") / NULLIF(SUM("TXNS") OVER () - "TXNS", 0) AS DECIMAL(9,3)) AS "TD_PCT_OTHER_DAYS"
FROM d ORDER BY "TXN_DT\""""

EXPOSURE_SQL = """SELECT COUNT(*) AS "OPEN_DNC",
       CAST(COALESCE(SUM("PENALTY_PAISE"), 0) / 100 AS DECIMAL(18,2)) AS "ACCRUED_RS",
       CAST(COALESCE(SUM("EXPOSURE_NEXT_24H_PAISE"), 0) / 100 AS DECIMAL(18,2)) AS "EXPOSURE_NEXT_24H_RS",
       CAST(COALESCE(SUM("NEW_ACCRUAL_24H_PAISE"), 0) / 100 AS DECIMAL(18,2)) AS "NEW_ACCRUAL_24H_RS",
       MIN("AS_OF_DT") AS "AS_OF_DT"
FROM "RECON"."PENALTY_EXPOSURE" WHERE "STATUS" = 'OPEN'"""

TOP_QUEUE_SQL = """SELECT "QUEUE_RANK", "EXC_ID", "CLASS", "TXN_TYPE", "TXN_DT", "DEADLINE_DT",
       CAST("AMOUNT_PAISE" / 100 AS DECIMAL(18,2)) AS "AMOUNT_RS",
       CAST("EXPOSURE_NEXT_24H_PAISE" / 100 AS DECIMAL(18,2)) AS "EXPOSURE_NEXT_24H_RS",
       CAST("NEW_ACCRUAL_24H_PAISE" / 100 AS DECIMAL(18,2)) AS "NEW_ACCRUAL_RS", "ACTION_NEEDED"
FROM "RECON"."WORK_QUEUE" ORDER BY "QUEUE_RANK" LIMIT 5"""

COMP_SQL = """SELECT "COMP_STATUS", COUNT(*) AS "CASES", CAST(SUM("COMP_GAP_PAISE") / 100 AS DECIMAL(18,2)) AS "GAP_RS"
FROM "RECON"."PENALTY_EXPOSURE" GROUP BY "COMP_STATUS" ORDER BY "COMP_STATUS\""""


def class_breakdown_sql(txn_dt: str, cycle_no) -> str:
    if not DATE.match(str(txn_dt)) or not str(cycle_no).isdigit():   # values come from a result set; still validated
        raise ValueError("bad window")
    return (f"""SELECT "CLASS", COUNT(*) AS "N" FROM "RECON"."EXCEPTIONS" WHERE "TXN_DT" = DATE '{txn_dt}' """
            f"""AND "FILE_CYCLE_NO" = {int(cycle_no)} GROUP BY "CLASS" ORDER BY "N" DESC""")


def _rows(r):  # list of dicts
    return [dict(zip(r["columns"], row)) for row in r["rows"]]


def _fmt(v) -> str:
    """Render a result value without inventing digits (commas only as thousands separators)."""
    s = str(v)
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        whole, _, frac = s.partition(".")
        sign = "-" if whole.startswith("-") else ""
        whole = whole.lstrip("-")
        whole = f"{int(whole):,}"
        return sign + whole + ("." + frac if frac else "")
    return s


def root_cause(query) -> dict:
    """query: callable(sql) -> {sql, columns, rows, ms}. Returns {text, results, proposal}."""
    results = [query(SPIKE_SQL)]
    spikes = _rows(results[0])
    if not spikes:
        return {"text": "There are no exceptions in any settlement window, so there is no spike to explain.",
                "results": results, "proposal": None}
    top = spikes[0]
    results.append(query(class_breakdown_sql(top["TXN_DT"], top["CYCLE_NO"])))
    classes = _rows(results[-1])
    results.append(query(FILES_SQL))
    files = _rows(results[-1])
    results.append(query(TD_SQL))
    td = {str(r["TXN_DT"]): r for r in _rows(results[-1])}

    lines = [f"Exceptions spiked for transactions on {top['TXN_DT']} in settlement cycle {top['CYCLE_NO']}: "
             f"{_fmt(top['EXCEPTIONS'])} exceptions, against a baseline of {_fmt(top['BASELINE_N'])} for that cycle "
             f"on the other days ({_fmt(top['X_BASELINE'])}x)."]
    if classes:
        c0 = classes[0]
        lines.append(f"The largest class in that window is {c0['CLASS']} with {_fmt(c0['N'])} exceptions.")
    window_file = next((f for f in files if str(f["SETTLEMENT_DT"]) == str(top["TXN_DT"])
                        and str(f["CYCLE_NO"]) == str(top["CYCLE_NO"])), None)
    proposal = None
    if window_file:
        if window_file["FILE_STATUS"] == "NOT_ARRIVED":
            lines.append(f"Root cause: the NPCI settlement file for {window_file['SETTLEMENT_DT']} cycle "
                         f"{window_file['CYCLE_NO']} was expected at {window_file['EXPECTED_TS']} and had not arrived by "
                         f"the recon cut-off {window_file['AS_OF']} ({_fmt(window_file['MINUTES_LATE'])} minutes overdue). "
                         f"Transactions in that window have no NPCI record yet, so they cannot be confirmed.")
            proposal = {"action_type": "CHASE_SETTLEMENT_FILE",
                        "target_ref": f"{window_file['SETTLEMENT_DT']}/{window_file['CYCLE_NO']}",
                        "rationale": lines[0] + " " + lines[-1]}
        else:
            lines.append(f"The settlement file for that window arrived {_fmt(window_file['MINUTES_LATE'])} minutes after "
                         f"its expected time ({window_file['EXPECTED_TS']}).")
    else:
        lines.append("The settlement file for that window arrived within the grace period, so a late file is not the cause.")
    t = td.get(str(top["TXN_DT"]))
    if t:
        lines.append(f"Technical declines on {t['TXN_DT']} were {_fmt(t['TD_PCT'])}% of switch transactions, "
                     f"against {_fmt(t['TD_PCT_OTHER_DAYS'])}% on the other days.")
    return {"text": " ".join(lines), "results": results, "proposal": proposal}


def exposure(query) -> dict:
    results = [query(EXPOSURE_SQL), query(TOP_QUEUE_SQL)]
    e = _rows(results[0])[0]
    top = _rows(results[1])
    text = (f"As of {e['AS_OF_DT']}, {_fmt(e['OPEN_DNC'])} DEBIT_NO_CREDIT cases are still open. "
            f"Compensation already accrued on them: Rs {_fmt(e['ACCRUED_RS'])}. If none is reversed, the total owed "
            f"tomorrow is Rs {_fmt(e['EXPOSURE_NEXT_24H_RS'])} (Rs {_fmt(e['NEW_ACCRUAL_24H_RS'])} of it is new accrual "
            f"by tomorrow, at the Rs/day rate of the RBI TAT circular [RBI-TAT-REF]).")
    proposal = None
    if top and top[0]["CLASS"] == "DEBIT_NO_CREDIT" and top[0]["ACTION_NEEDED"] == "RESOLVE_DEBIT_NO_CREDIT":
        q = top[0]
        text += (f" Highest-ranked item: {q['EXC_ID']} ({q['TXN_TYPE']}, Rs {_fmt(q['AMOUNT_RS'])}, transaction date "
                 f"{q['TXN_DT']}, TAT deadline {q['DEADLINE_DT']}). Reversing it avoids Rs {_fmt(q['NEW_ACCRUAL_RS'])} tomorrow, "
                 f"the same as any accruing case; it ranks first because it has waited longest "
                 f"(Rs {_fmt(q['EXPOSURE_NEXT_24H_RS'])} owed tomorrow in total).")
        proposal = {"action_type": "POST_REVERSAL", "target_ref": q["EXC_ID"],
                    "rationale": f"Rank 1 in the work queue: adds Rs {_fmt(q['NEW_ACCRUAL_RS'])} tomorrow if not reversed, "
                                 f"Rs {_fmt(q['EXPOSURE_NEXT_24H_RS'])} owed in total."}
    return {"text": text, "results": results, "proposal": proposal}


def compensation(query) -> dict:
    results = [query(COMP_SQL)]
    rows = _rows(results[0])
    parts = [f"{r['COMP_STATUS']}: {_fmt(r['CASES'])} cases" + (f" (gap Rs {_fmt(r['GAP_RS'])})" if r["COMP_STATUS"] in
             ("MISSING", "UNDERPAID") else "") for r in rows]
    text = ("Suo-moto compensation check for DEBIT_NO_CREDIT cases (the RBI TAT circular requires it without a complaint [RBI-TAT-SUOMOTO]): "
            + "; ".join(parts) + ".")
    return {"text": text, "results": results, "proposal": None}
