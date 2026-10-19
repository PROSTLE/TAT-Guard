"""Offline tests for ui/api.py input validation (no database: a fake q records what would be sent)."""
import pytest

from ui import api


class FakeQ:
    def __init__(self):
        self.calls = []

    def __call__(self, sql, params=None):
        self.calls.append((sql, params or {}))
        return {"columns": ["N", "TAT_STATE", "CLASS"], "rows": [], "ms": 0}


@pytest.mark.parametrize("args", [{"q": "x' OR 1=1"}, {"q": "a b"}, {"state": "NOPE"}, {"class": "drop table"},
                                  {"class": "LATE_FILE;"}])
def test_queue_rejects_bad_input_before_any_sql(args):
    q = FakeQ()
    with pytest.raises(ValueError):
        api.queue(q, args)
    assert q.calls == []


def test_queue_values_are_parameters_not_sql_text():
    q = FakeQ()
    try:
        api.queue(q, {"q": "TGU9D3", "state": "OVERDUE", "class": "DEBIT_NO_CREDIT", "sort": "owed", "page": "2", "size": "10"})
    except KeyError:
        pass  # the fake returns no "N" row for the count; the first statement is what we check
    sql, params = q.calls[0]
    assert "TGU9D3" not in sql and params["s"] == "TGU9D3" and params["sp"] == "TGU9D3%"
    assert params["st"] == "OVERDUE" and params["cls"] == "DEBIT_NO_CREDIT"
    assert params["lim"] == 10 and params["off"] == 10
    assert '"EXPOSURE_NEXT_24H_PAISE" DESC' in sql


def test_unknown_sort_and_page_size_fall_back_to_defaults():
    q = FakeQ()
    try:
        api.queue(q, {"sort": "1; DROP", "size": "7"})
    except KeyError:
        pass
    sql, params = q.calls[0]
    assert '"QUEUE_RANK" ASC' in sql and params["lim"] == 25


@pytest.mark.parametrize("name", ["../.env", "..\\.env", "x/../../.env", "report.md.exe", "", "a" * 200 + ".md"])
def test_report_names_are_restricted(name):
    with pytest.raises(ValueError):
        api.report_text(name)


def test_transaction_detail_rejects_non_ids():
    with pytest.raises(ValueError):
        api.transaction_detail(FakeQ(), "1' OR '1'='1")


def test_tat_states_match_the_view_definition():
    view = (api.ROOT / "sql" / "30_penalty_view.sql").read_text(encoding="utf-8")
    for s in api.TAT_STATES:
        assert f"'{s}'" in view
