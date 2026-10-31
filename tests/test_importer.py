"""Offline tests for ui/importer.py: file checks, the public-or-synthetic confirmation, and the one-import-at-a-time rule."""
import io

import pytest

from recon import pipeline
from ui import importer


def test_file_columns_follow_the_schema_sql():
    cols = importer.file_columns()
    assert set(cols) == {f for f, _ in pipeline.LOADS}
    assert cols["switch_log.csv"] == ["UPI_TXN_ID", "RRN", "TXN_TS", "AMOUNT_PAISE", "STATUS", "RESP_CODE", "CHANNEL"]
    assert "NARRATION" in cols["cbs_ledger.csv"]


@pytest.mark.parametrize("head", ['"UPI_TXN_ID","RRN","TXN_TS","AMOUNT_PAISE","STATUS","RESP_CODE","CHANNEL"\n',
                                  "﻿upi_txn_id,rrn,txn_ts,amount_paise,status,resp_code,channel\n"])
def test_header_accepts_the_layout_with_or_without_bom_and_quotes(tmp_path, head):
    p = tmp_path / "s.csv"
    p.write_text(head, encoding="utf-8")
    assert importer.check_header(p, importer.file_columns()["switch_log.csv"]) is None


def test_header_refuses_wrong_order_because_import_maps_by_position(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text("RRN,UPI_TXN_ID,TXN_TS,AMOUNT_PAISE,STATUS,RESP_CODE,CHANNEL\n", encoding="utf-8")
    assert "Expected the columns" in importer.check_header(p, importer.file_columns()["switch_log.csv"])


def test_upload_keeps_a_good_file_and_removes_a_bad_one(tmp_path, monkeypatch):
    monkeypatch.setattr(importer, "UPLOADS", tmp_path)
    good = ",".join(importer.file_columns()["switch_log.csv"]).encode() + b"\n"
    r = importer.save_upload("", "switch_log.csv", io.BytesIO(good), len(good))
    assert (tmp_path / r["upload_id"] / "switch_log.csv").exists()
    with pytest.raises(ValueError, match="Expected the columns"):
        importer.save_upload(r["upload_id"], "cbs_ledger.csv", io.BytesIO(good), len(good))
    assert not (tmp_path / r["upload_id"] / "cbs_ledger.csv").exists()


def test_upload_refuses_unknown_slots_and_bad_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(importer, "UPLOADS", tmp_path)
    with pytest.raises(ValueError, match="Unknown file slot"):
        importer.save_upload("", "../../evil.csv", io.BytesIO(b"x"), 1)
    with pytest.raises(ValueError, match="Bad upload id"):
        importer.save_upload("../..", "switch_log.csv", io.BytesIO(b"x"), 1)


def test_a_truncated_upload_is_not_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(importer, "UPLOADS", tmp_path)
    with pytest.raises(ValueError, match="stopped before"):
        importer.save_upload("", "switch_log.csv", io.BytesIO(b"abc"), 10)
    assert not list(tmp_path.rglob("*.csv"))


@pytest.mark.parametrize("source", ["upload", "schema"])
def test_own_data_needs_the_public_or_synthetic_confirmation(source):
    with pytest.raises(ValueError, match="public or synthetic"):
        importer.start({"source": source})


def test_bad_source_and_bad_cutoff_are_refused():
    with pytest.raises(ValueError, match="Pick where"):
        importer.start({"source": "nope"})
    with pytest.raises(ValueError, match="Cut-off"):
        importer.start({"source": "upload", "as_of": "'; DROP TABLE x", "confirm_public": True})


@pytest.mark.parametrize("ending,expected", [(bytes([13, 10]), "CRLF"), (bytes([10]), "LF")])
def test_import_uses_the_files_own_line_ending(tmp_path, ending, expected):
    p = tmp_path / "s.csv"
    p.write_bytes(b"A,B" + ending + b"1,2" + ending)
    assert pipeline.csv_params(p)["row_separator"] == expected


def test_the_database_reason_is_shown_not_the_wrapper():
    class Wrapped(Exception):
        exceptions = (ValueError("data exception - invalid timestamp in line 2"),)
    assert importer._why(Wrapped("Error in executing `import_from_callback`")) == "data exception - invalid timestamp in line 2"


def test_stage_never_offered_as_a_source():
    class C:
        def execute(self, sql):
            cols = importer.file_columns()
            rows = [(pipeline.STAGE, t.split(".")[1], c) for f, t in pipeline.LOADS for c in cols[f]]
            rows += [("MINE", t.split(".")[1], c) for f, t in pipeline.LOADS for c in cols[f]]
            return type("R", (), {"fetchall": lambda self: rows})()
    assert importer.schemas(C()) == ["MINE"]


def test_only_one_import_at_a_time(tmp_path, monkeypatch):
    monkeypatch.setattr(importer, "UPLOADS", tmp_path)
    for f, _ in pipeline.LOADS:
        (tmp_path / "0123456789abcdef").mkdir(exist_ok=True)
        (tmp_path / "0123456789abcdef" / f).write_text("x", encoding="utf-8")
    monkeypatch.setitem(importer.JOB, "status", "running")
    with pytest.raises(ValueError, match="already running"):
        importer.start({"source": "upload", "upload_id": "0123456789abcdef", "confirm_public": True})
    importer.JOB.clear()
    importer.JOB.update(status="idle")
