"""Offline tests for agent/actions.py decide(): no database, a fake connection records every statement."""
import inspect

import pytest

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
            return _Stmt([("POST_REVERSAL", "ETGU0000000000000001", "agent:deterministic")])
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


def test_a_person_cannot_approve_their_own_proposal(monkeypatch):
    class Own(FakeC):
        def execute(self, sql, params=None):
            self.sql.append(sql)
            return _Stmt([("POST_REVERSAL", "ETGU0000000000000001", "analyst:Priya")])

    monkeypatch.setattr(actions, "MAKER_CHECKER", True)
    C = Own()
    with pytest.raises(actions.ActionError, match="second person"):
        actions.decide(C, "PA-000000000001", True, " priya ")
    assert not any(s.lstrip().startswith("UPDATE") for s in C.sql), "refused approval must not claim the action"


def test_same_person_only_matches_the_proposing_analyst():
    assert actions.same_person("analyst:Priya", " PRIYA ")
    assert not actions.same_person("agent:deterministic", "deterministic")
    assert not actions.same_person("analyst:Priya", "Ravi")


def test_a_person_can_reject_their_own_proposal():
    class Own(FakeC):
        def execute(self, sql, params=None):
            self.sql.append(sql)
            if sql.lstrip().startswith("UPDATE"):
                return _Stmt(rowcount=1)
            return _Stmt([("POST_REVERSAL", "ETGU0000000000000001", "analyst:Priya")])

    assert actions.decide(Own(), "PA-000000000001", False, "Priya")["status"] == "REJECTED"


def test_recon_failure_after_a_posting_stays_executed_and_is_reported(monkeypatch):
    class Posted(FakeC):
        def execute(self, sql, params=None):
            self.sql.append(sql)
            if sql.lstrip().startswith("UPDATE"):
                return _Stmt(rowcount=1)
            return _Stmt([("POST_REVERSAL", "ETGU0000000000000001", "agent:deterministic")])

    def boom(C, T):
        raise RuntimeError("simulated recon failure")

    monkeypatch.setattr(actions, "snapshot", lambda C, ref=None: {})
    monkeypatch.setattr(actions, "_eligible", lambda C, t, r: None)
    monkeypatch.setattr(actions, "_execution_sql", lambda C, t, r, a: 'INSERT INTO "RAW"."CBS_LEDGER" VALUES (1)')
    monkeypatch.setattr(actions.pipeline, "cmd_recon", boom)
    out = actions.decide(Posted(), "PA-000000000001", True, "reviewer")
    assert out["status"] == "EXECUTED" and "simulated recon failure" in out["error"]


def test_second_proposal_is_refused_while_a_posting_is_not_reconciled():
    class Stale(FakeC):
        def execute(self, sql, params=None):
            self.sql.append(sql)
            return _Stmt([("PA-00000000AAAA",)])     # still eligible, and an EXECUTED action exists

    with pytest.raises(actions.ActionError, match="not picked it up"):
        actions._eligible(Stale(), "POST_REVERSAL", "ETGU0000000000000001")


def test_reversal_posts_what_is_still_outstanding_not_the_full_debit():
    src = inspect.getsource(actions._execution_sql)
    assert 'e."DEBIT_TOTAL_PAISE" - e."REVERSED_PAISE"' in src
