"""Offline tests for agent/actions.py decide(): no database, a fake connection records every statement."""
from agent import actions


class _Stmt:
    def __init__(self, rows=(), rowcount=0):
        self._rows, self._rc = list(rows), rowcount

    def fetchall(self):
        return self._rows

    def rowcount(self):
        return self._rc


class FakeC:
    """Knows one PROPOSED action; any read of the work queue (the snapshot) fails like a dropped query would."""

    def __init__(self):
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        if '"WORK_QUEUE"' in sql:
            raise RuntimeError("simulated failure while reading the before/after snapshot")
        if sql.lstrip().startswith("SELECT") and '"PROPOSED_ACTIONS"' in sql:
            return _Stmt([("POST_REVERSAL", "ETGU0000000000000001")])
        if sql.lstrip().startswith("UPDATE"):
            return _Stmt(rowcount=1)
        return _Stmt()


def test_failed_snapshot_after_claim_still_logs_and_sets_a_final_status():
    C = FakeC()
    out = actions.decide(C, "PA-000000000001", True, "reviewer")
    assert out["status"] == "FAILED" and "simulated failure" in out["error"]
    assert any('INSERT INTO "AUDIT"."ACTION_LOG"' in s for s in C.sql), "approved action left without an audit row"
    assert 'SET "STATUS" = {s} WHERE' in C.sql[-1], "final status update must be the last statement"
    assert not any('INSERT INTO "RAW"."CBS_LEDGER"' in s for s in C.sql), "nothing may be posted after a failed check"


def test_approval_needs_a_named_human():
    C = FakeC()
    try:
        actions.decide(C, "PA-000000000001", True, "  ")
    except actions.ActionError:
        assert C.sql == []
    else:
        raise AssertionError("blank approver accepted")
