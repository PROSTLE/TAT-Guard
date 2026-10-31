"""Human-approved actions: PROPOSED -> (human) APPROVED -> executed -> AUDIT.ACTION_LOG (01 Phase 4).

Rules enforced here, on the backend's admin connection (the agent's DB user cannot write at all):
  * Only the action types in ACTION_TYPES exist. Each has an eligibility query and a FIXED SQL template whose
    values are looked up from the database at execution time. No SQL text from the agent/LLM is ever executed;
    the agent can only supply (action_type, target_ref, rationale), and rationale is stored as data.
  * A proposal is executed only after a human approves it, exactly once (UPDATE ... WHERE STATUS='PROPOSED').
  * Maker-checker: a person cannot approve their own proposal (actions.require_second_person in recon/config.yaml).
    They can reject it, which withdraws it.
  * A posting is never repeated: if the recon after a posting fails, the case still looks eligible, so the action stays
    EXECUTED and any new proposal for that target is refused until a recon has picked the posting up.
  * Every execution writes AUDIT.ACTION_LOG: who, when, the exact SQL executed, before/after snapshots.

On this SYNTHETIC data, executing POST_REVERSAL / PAY_COMPENSATION simulates the bank's CBS posting (one credit
row in RAW.CBS_LEDGER) and re-runs the recon. CHASE_SETTLEMENT_FILE changes no data; it is logged for operations.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import sys
import uuid

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from recon import pipeline  # noqa: E402

CFG = yaml.safe_load(open(ROOT / "recon" / "config.yaml", encoding="utf-8"))
NARR = CFG["actions"]["narration"]

ACTION_TYPES = {
    "POST_REVERSAL": "Reverse the customer's debit for an OPEN DEBIT_NO_CREDIT exception (stops the TAT penalty clock)",
    "PAY_COMPENSATION": "Credit the missing/short suo-moto compensation for a reversed case past TAT",
    "CHASE_SETTLEMENT_FILE": "Ask operations to chase an overdue NPCI settlement file (no data change)",
}
FILE_REF = re.compile(r"^(\d{4}-\d{2}-\d{2})/(\d{1,3})$")       # CHASE_SETTLEMENT_FILE target: SETTLEMENT_DT/CYCLE_NO
# Row-level eligibility of the exception-targeted action types, as SQL predicates over columns that RECON.EXCEPTIONS /
# RECON.PENALTY_EXPOSURE and RECON.WORK_QUEUE share. _eligible() checks a proposal with them; ui/api.py uses the same
# predicates to tell the page which action a queue row can take, so the page never re-implements this rule.
PROPOSE_WHEN = {
    "POST_REVERSAL": """"CLASS" = 'DEBIT_NO_CREDIT' AND "STATUS" = 'OPEN'""",
    "PAY_COMPENSATION": """"COMP_STATUS" IN ('MISSING', 'UNDERPAID')""",
}
ANALYST_PREFIX = "analyst:"       # CREATED_BY of a person's proposal; the agent's start with "agent:"
MAKER_CHECKER = bool(CFG["actions"]["require_second_person"])
# Lifecycle of AUDIT.PROPOSED_ACTIONS.STATUS: PROPOSED -> APPROVED (claimed) -> EXECUTED | LOGGED | FAILED, or REJECTED
STATUSES = ("PROPOSED", "APPROVED", "EXECUTED", "LOGGED", "REJECTED", "FAILED")


class ActionError(ValueError):
    pass


def _check_templates():
    """Fail loudly if a config change would make executed postings invisible to the matcher."""
    kinds = {k["kind"]: k["pattern"] for k in CFG["narration_kinds"]}
    ref = re.compile(CFG["matching"]["ref_pattern"])
    sample_rrn = "123456789012"   # our synthetic RRNs are 12 digits (generator/config.yaml ids.rrn_digits)
    for action, kind in (("POST_REVERSAL", "REVERSAL"), ("PAY_COMPENSATION", "COMPENSATION")):
        text = NARR[action].format(rrn=sample_rrn, rupees=100)
        if not re.search(kinds[kind], text):
            raise RuntimeError(f"actions.narration.{action} {text!r} is not typed {kind} by narration_kinds")
        m = ref.search(text)
        if not m or (m.group(1) if m.groups() else m.group(0)) != sample_rrn:
            raise RuntimeError(f"matching.ref_pattern does not extract the RRN from {text!r}")


_check_templates()


def _one(C, sql, params=None):
    rows = C.execute(sql, params or {}).fetchall()
    return rows[0] if rows else None


def _as_of(C) -> str:
    return _one(C, """SELECT "PARAM_VALUE" FROM "RECON"."SETTINGS" WHERE "PARAM_NAME" = 'as_of'""")[0]


def snapshot(C, target_ref: str | None = None) -> dict:
    """Totals shown before/after an action (all from live queries)."""
    tot = _one(C, """SELECT COUNT(*), COALESCE(SUM("EXPOSURE_NEXT_24H_PAISE"), 0), COALESCE(SUM("NEW_ACCRUAL_24H_PAISE"), 0),
                            CAST(COALESCE(SUM("EXPOSURE_NEXT_24H_PAISE"), 0) / 100 AS DECIMAL(18,2)),
                            CAST(COALESCE(SUM("NEW_ACCRUAL_24H_PAISE"), 0) / 100 AS DECIMAL(18,2))
                     FROM "RECON"."WORK_QUEUE" """)
    snap = {"as_of": _as_of(C), "queue_rows": int(tot[0]), "exposure_next_24h_paise": int(tot[1]),
            "new_accrual_24h_paise": int(tot[2]), "exposure_next_24h_rs": str(tot[3]), "new_accrual_24h_rs": str(tot[4])}
    if target_ref:
        r = C.execute("""SELECT e."EXC_ID", e."CLASS", e."STATUS", e."REVERSAL_DT", e."COMP_PAISE",
                                p."PENALTY_PAISE", p."EXPOSURE_NEXT_24H_PAISE", p."COMP_STATUS", p."COMP_GAP_PAISE"
                         FROM "RECON"."EXCEPTIONS" e LEFT JOIN "RECON"."PENALTY_EXPOSURE" p ON p."EXC_ID" = e."EXC_ID"
                         WHERE e."EXC_ID" = {t}""", {"t": target_ref})
        cols = r.column_names()
        row = r.fetchone()
        snap["target"] = {c: (None if v is None else str(v)) for c, v in zip(cols, row)} if row else None
    return snap


def _eligible(C, action_type: str, target_ref: str) -> None:
    if action_type == "POST_REVERSAL":
        ok = _one(C, 'SELECT 1 FROM "RECON"."EXCEPTIONS" WHERE "EXC_ID" = {t} AND ' + PROPOSE_WHEN[action_type],
                  {"t": target_ref})
        why = "target must be an OPEN DEBIT_NO_CREDIT exception (EXC_ID)"
    elif action_type == "PAY_COMPENSATION":
        ok = _one(C, 'SELECT 1 FROM "RECON"."PENALTY_EXPOSURE" WHERE "EXC_ID" = {t} AND ' + PROPOSE_WHEN[action_type],
                  {"t": target_ref})
        why = "target must be a reversed DEBIT_NO_CREDIT whose COMP_STATUS is MISSING or UNDERPAID (EXC_ID)"
    elif action_type == "CHASE_SETTLEMENT_FILE":
        m = FILE_REF.match(target_ref)
        ok = m and _one(C, """SELECT 1 FROM "RAW"."SETTLEMENT_FILE_LOG" WHERE "SETTLEMENT_DT" = {d}
                              AND "CYCLE_NO" = {c!d} AND "ARRIVED_TS" IS NULL""", {"d": m.group(1), "c": m.group(2)})
        why = "target must be SETTLEMENT_DT/CYCLE_NO of a settlement file that has not arrived, e.g. 2026-10-07/3"
    else:
        raise ActionError(f"unknown action_type {action_type!r}; allowed: {sorted(ACTION_TYPES)}")
    if not ok:
        raise ActionError(f"{action_type} not eligible for {target_ref!r}: {why}")
    if action_type in PROPOSE_WHEN:
        done = _one(C, """SELECT "ACTION_ID" FROM "AUDIT"."PROPOSED_ACTIONS" WHERE "ACTION_TYPE" = {a}
                          AND "TARGET_REF" = {t} AND "STATUS" = 'EXECUTED'""", {"a": action_type, "t": target_ref})
        if done:
            raise ActionError(f"{done[0]} already posted {action_type} for {target_ref!r} and the case still shows as "
                              "eligible, so the reconciliation has not picked it up. Run the reconciliation first.")


def same_person(created_by: str, user: str) -> bool:
    return str(created_by or "").strip().casefold() == (ANALYST_PREFIX + str(user or "").strip()).casefold()


def propose(C, action_type: str, target_ref: str, rationale: str, evidence_sql: str = "", created_by: str = "agent") -> dict:
    action_type, target_ref = str(action_type).strip().upper(), str(target_ref).strip()
    _eligible(C, action_type, target_ref)
    dup = _one(C, """SELECT "ACTION_ID" FROM "AUDIT"."PROPOSED_ACTIONS" WHERE "ACTION_TYPE" = {a}
                     AND "TARGET_REF" = {t} AND "STATUS" = 'PROPOSED'""", {"a": action_type, "t": target_ref})
    if dup:
        return {"action_id": dup[0], "status": "PROPOSED", "duplicate": True}
    aid = "PA-" + uuid.uuid4().hex[:12].upper()
    C.execute("""INSERT INTO "AUDIT"."PROPOSED_ACTIONS" ("ACTION_ID", "CREATED_TS", "CREATED_BY", "ACTION_TYPE",
                 "TARGET_REF", "RATIONALE", "EVIDENCE_SQL", "STATUS") VALUES ({a}, {ts}, {by}, {t}, {r}, {rat}, {ev}, 'PROPOSED')""",
              {"a": aid, "ts": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "by": str(created_by)[:100],
               "t": action_type, "r": target_ref, "rat": str(rationale)[:2000], "ev": str(evidence_sql)[:20000]})
    return {"action_id": aid, "status": "PROPOSED", "duplicate": False}


def _execution_sql(C, action_type: str, target_ref: str, action_id: str) -> str | None:
    """Builds the exact statement to run from DB lookups (fixed templates; nothing from the proposal text)."""
    if action_type == "CHASE_SETTLEMENT_FILE":
        return None
    as_of = _as_of(C)
    if action_type == "POST_REVERSAL":
        r = _one(C, """SELECT e."RRN", r."ACCOUNT_NO_MASKED", e."DEBIT_TOTAL_PAISE" - e."REVERSED_PAISE"
                       FROM "RECON"."EXCEPTIONS" e
                       JOIN "RECON"."CBS_MATCH" m ON m."RRN" = e."RRN" AND m."KIND" = 'DEBIT'
                       JOIN "RECON"."CBS_REF" r ON r."CBS_ENTRY_ID" = m."CBS_ENTRY_ID"
                       WHERE e."EXC_ID" = {t} ORDER BY r."POST_TS" LIMIT 1""", {"t": target_ref})
        rrn, acct, amount = r
        narr = NARR["POST_REVERSAL"].format(rrn=rrn)
    else:  # PAY_COMPENSATION
        r = _one(C, """SELECT p."RRN", r."ACCOUNT_NO_MASKED", p."COMP_GAP_PAISE"
                       FROM "RECON"."PENALTY_EXPOSURE" p
                       JOIN "RECON"."CBS_MATCH" m ON m."RRN" = p."RRN" AND m."KIND" = 'DEBIT'
                       JOIN "RECON"."CBS_REF" r ON r."CBS_ENTRY_ID" = m."CBS_ENTRY_ID"
                       WHERE p."EXC_ID" = {t} ORDER BY r."POST_TS" LIMIT 1""", {"t": target_ref})
        rrn, acct, amount = r
        narr = NARR["PAY_COMPENSATION"].format(rrn=rrn, rupees=int(amount) // 100)
    return C.format.format(
        """INSERT INTO "RAW"."CBS_LEDGER" ("CBS_ENTRY_ID", "ACCOUNT_NO_MASKED", "POST_TS", "DR_CR", "AMOUNT_PAISE", "NARRATION")
VALUES ({id}, {acct}, {ts}, 'CR', {amt!d}, {narr})""",
        id="A" + action_id, acct=acct, ts=as_of, amt=int(amount), narr=narr)


def decide(C, action_id: str, approve: bool, user: str) -> dict:
    user = str(user or "").strip()[:100]
    if not user:
        raise ActionError("a named human approver is required")
    row = _one(C, """SELECT "ACTION_TYPE", "TARGET_REF", "CREATED_BY" FROM "AUDIT"."PROPOSED_ACTIONS" WHERE "ACTION_ID" = {a}""",
               {"a": action_id})
    if not row:
        raise ActionError(f"no action {action_id}")
    action_type, target_ref, created_by = row
    if approve and MAKER_CHECKER and same_person(created_by, user):
        raise ActionError(f"{user} proposed {action_id}, so a second person must approve it")
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    claimed = C.execute("""UPDATE "AUDIT"."PROPOSED_ACTIONS" SET "STATUS" = {s}, "DECIDED_BY" = {u}, "DECIDED_TS" = {ts}
                           WHERE "ACTION_ID" = {a} AND "STATUS" = 'PROPOSED'""",
                        {"s": "APPROVED" if approve else "REJECTED", "u": user, "ts": now, "a": action_id}).rowcount()
    if claimed != 1:
        raise ActionError(f"{action_id} is not in status PROPOSED (already decided)")
    if not approve:
        return {"action_id": action_id, "status": "REJECTED"}

    # From here the action is claimed (APPROVED). Every path below must end in an ACTION_LOG row and a final status,
    # so the snapshots are inside the try blocks: a failed read must not leave the action stuck at APPROVED.
    snap_ref = target_ref if action_type != "CHASE_SETTLEMENT_FILE" else None
    before, outcome, sql, err, recon_err = {}, "EXECUTED", None, None, None
    try:
        before = snapshot(C, snap_ref)
        _eligible(C, action_type, target_ref)          # still eligible at execution time?
        sql = _execution_sql(C, action_type, target_ref, action_id)
        if sql is None:
            outcome, sql = "LOGGED", "-- no database change: request logged for operations"
        else:
            C.execute(sql)
            if CFG["actions"].get("recon_after_execute"):
                T = pipeline.Timer(C, "act-" + action_id[3:], "after-action")
                try:
                    pipeline.cmd_recon(C, T)
                    T.flush()
                except Exception as e:  # the money moved, so this stays EXECUTED, not FAILED: see _eligible
                    recon_err = f"posted, but the reconciliation did not finish: {type(e).__name__}: {e}"[:2000]
    except Exception as e:  # recorded, not swallowed: status FAILED + log row
        outcome, err = "FAILED", f"{type(e).__name__}: {e}"[:2000]
    try:
        after = snapshot(C, snap_ref)
    except Exception as e:
        after = {"snapshot_error": f"{type(e).__name__}: {e}"[:2000]}
    if err or recon_err:
        after["error"] = err or recon_err
    C.execute("""INSERT INTO "AUDIT"."ACTION_LOG" ("LOG_ID", "ACTION_ID", "EXECUTED_BY", "EXECUTED_TS", "EXECUTED_SQL",
                 "BEFORE_JSON", "AFTER_JSON", "OUTCOME") VALUES ({l}, {a}, {u}, {ts}, {sql}, {b}, {af}, {o})""",
              {"l": "L-" + uuid.uuid4().hex[:12].upper(), "a": action_id, "u": user,
               "ts": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "sql": (sql or "")[:20000],
               "b": json.dumps(before)[:20000], "af": json.dumps(after)[:20000], "o": outcome})
    C.execute("""UPDATE "AUDIT"."PROPOSED_ACTIONS" SET "STATUS" = {s} WHERE "ACTION_ID" = {a}""",
              {"s": outcome, "a": action_id})
    return {"action_id": action_id, "status": outcome, "executed_sql": sql, "before": before, "after": after, "error": err or recon_err}
