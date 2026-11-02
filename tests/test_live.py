"""Offline tests for ui/live.py: what a payment writes for each scenario, and what is refused before any SQL."""
import datetime as dt
import re

import pytest

from recon import pipeline
from ui import live

GOOD = {"payee": "Ravi Kumar", "amount": 1250, "txn_type": "P2P", "bank": "BNK03", "scenario": "debit_no_credit"}
TS = dt.datetime(2026, 10, 8, 7, 30, 15)
RRN = "123456789012"
REF = re.compile(pipeline.yaml.safe_load(open(pipeline.ROOT / "recon" / "config.yaml", encoding="utf-8"))["matching"]["ref_pattern"])


def rows(scenario):
    return live.build_rows(live.validate_payment({**GOOD, "scenario": scenario}), TS, "TGLABC", RRN)


@pytest.mark.parametrize("bad", [
    {"payee": "x'); DROP TABLE RAW.SWITCH_LOG;--"}, {"payee": "<img src=x>"}, {"payee": ""}, {"payee": "9lives"}, {"payee": "a" * 41},
    {"amount": 0}, {"amount": -5}, {"amount": 0.5}, {"amount": 10 ** 9}, {"amount": "NaN"}, {"amount": "Infinity"}, {"amount": None}, {"amount": "abc"},
    {"txn_type": "IMPS"}, {"bank": "BNK99"}, {"bank": "BNK00"}, {"bank": "BNK01' OR 1=1"}, {"scenario": "drop"}])
def test_bad_payments_are_refused_before_any_sql(bad):
    with pytest.raises(ValueError):
        live.validate_payment({**GOOD, **bad})


def test_amount_becomes_integer_paise():
    assert live.validate_payment({**GOOD, "amount": "19.99"})["paise"] == 1999


def test_debit_no_credit_is_debited_but_failed_at_npci():
    r = rows("debit_no_credit")
    assert r["npci"]["STATUS"] == "FAILED" and r["switch"]["STATUS"] != "SUCCESS" and len(r["ledger"]) == 1
    assert r["switch"]["RESP_CODE"] == r["npci"]["RESP_CODE"] and r["switch"]["RESP_CODE"].startswith("TD")


def test_duplicate_posts_two_debits_with_the_same_reference():
    r = rows("duplicate")
    assert len(r["ledger"]) == 2 and r["ledger"][0]["NARRATION"] == r["ledger"][1]["NARRATION"]
    assert r["ledger"][0]["CBS_ENTRY_ID"] != r["ledger"][1]["CBS_ENTRY_ID"]


def test_amount_mismatch_differs_in_the_ledger_only():
    r = rows("amount_mismatch")
    assert r["switch"]["AMOUNT_PAISE"] == r["npci"]["AMOUNT_PAISE"] != r["ledger"][0]["AMOUNT_PAISE"]


def test_no_debit_writes_no_ledger_row():
    assert rows("no_debit")["ledger"] == []


def test_switch_id_missing_leaves_only_the_rrn_on_the_switch_row():
    r = rows("switch_id_missing")
    assert r["switch"]["UPI_TXN_ID"] is None and r["switch"]["RRN"] == RRN and r["npci"]["UPI_TXN_ID"] == "TGLABC"


@pytest.mark.parametrize("scenario", ["clean", "messy_narration", "debit_no_credit", "duplicate", "amount_mismatch"])
def test_the_matcher_can_read_the_reference_from_the_ledger_note(scenario):
    assert any(RRN in m for m in REF.findall(rows(scenario)["ledger"][0]["NARRATION"]))


def test_no_reference_note_really_has_none():
    narration = rows("no_reference")["ledger"][0]["NARRATION"]
    assert RRN not in narration and not REF.search(narration)


def test_settlement_cycle_follows_the_time_of_day():
    assert rows("clean")["npci"]["CYCLE_NO"] == 2      # 07:30 is in the second of four cycles


def test_nothing_tells_the_rows_what_was_injected():
    for scenario in live.SCENARIOS:
        assert scenario not in str(rows(scenario)).lower()


def test_every_expected_class_is_a_class_the_sql_can_produce():
    classify = (pipeline.SQL / "15_classify.sql").read_text(encoding="utf-8")
    for s in live.SCENARIOS.values():
        assert s["expected"] is None or f"'{s['expected']}'" in classify


def test_every_pipeline_step_has_a_label_on_the_page():
    assert set(live.STEPS) == {f"recon {f}" for f in pipeline.RECON_STEPS}


class FakeFormat:
    @staticmethod
    def format(sql, **kw):
        return sql.replace("{v}", "'" + kw["v"].replace("'", "''") + "'")


class FakeC:
    format = FakeFormat


def test_insert_quotes_values_and_writes_null_for_a_missing_id():
    sql = live.insert_sql(FakeC, "switch", rows("switch_id_missing")["switch"])
    assert sql.startswith('INSERT INTO "RAW"."SWITCH_LOG"') and "VALUES (NULL, '123456789012'" in sql


def test_payee_token_keeps_only_safe_characters():
    assert live.payee_token("O'Brien J.") == "OBRIENJ"
    assert live.payee_token("...") == "PAYEE"


def test_plain_sql_drops_comments_and_stops_at_the_first_statement():
    text = "-- why\nCREATE TABLE A AS\nSELECT 1;\nDROP TABLE B;"
    assert live.plain_sql(text) == "CREATE TABLE A AS\nSELECT 1"


def test_plan_rows_keep_how_the_data_moved_and_skip_noise():
    parts = [(1, 1, "SCAN", "DUAL", 1, 1, 0.0), (1, 2, "INSERT", "tmp_subselect0", 0, 1, 0.0), (1, 3, "SCAN", "NPCI_SETTLEMENT", "952333", "952333", 0.0),
             (1, 4, "JOIN", "SWITCH_LOG", "1000008", "950431", 0.117), (1, 5, "COMMIT", None, None, None, 0.0)]
    assert live.plan_rows(parts) == [{"part": "SCAN", "object": "NPCI_SETTLEMENT", "rows_in": 952333, "rows_out": 952333, "ms": 0},
                                     {"part": "JOIN", "object": "SWITCH_LOG", "rows_in": 1000008, "rows_out": 950431, "ms": 117}]
