"""Connect & Import: choose an Exasol database, load a dataset into it, re-run the reconciliation.

Every number on the page comes from the RAW and RECON schemas, so this module is the one way (besides
recon/pipeline.py on the command line) that data gets there. It adds no loading logic of its own: all three sources go
through recon/pipeline.py, so an import from the page and a run from the terminal do the same work and log the same timings.

    sample   a dataset under data/ written by generator/generate.py
    upload   four CSV files in the stand-in layouts of sql/00_schemas.sql, sent from the browser
    schema   an existing Exasol schema that already holds the four tables

The project takes public or synthetic data only, so a file or schema needs the user's confirmation that it is one of
those (the same check as the `synthetic` flag in a generator manifest). There is no login: the server binds to
127.0.0.1. A password typed on the page is kept in this process's memory and is never written to disk or sent back.
"""
from __future__ import annotations

import csv
import json
import os
import pathlib
import re
import secrets
import shutil
import tempfile
import threading
import time
import uuid

import pyexasol

from agent import setup_agent_user
from recon import pipeline

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
READER_STEP = "read-only user"
CHECK_STEP = "check data"
SAMPLE_NAME = "Synthetic sample dataset"
AS_OF = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?$")
UPLOAD_ID = re.compile(r"^[0-9a-f]{16}$")
CHUNK = 1024 * 1024
UPLOADS = pathlib.Path(tempfile.gettempdir()) / "tatguard_uploads"

LOCK = threading.Lock()
JOB: dict = {"status": "idle"}
SWITCHED = {"reader_needed": False}


def file_columns() -> dict[str, list[str]]:
    """Required header per CSV, read from sql/00_schemas.sql so the layouts live in one place."""
    text = (pipeline.SQL / "00_schemas.sql").read_text(encoding="utf-8")
    tables = {m.group(1): m.group(2) for m in re.finditer(r"CREATE OR REPLACE TABLE RAW\.(\w+) \((.*?)\n\);", text, re.S)}
    out = {}
    for fname, table in pipeline.LOADS:
        lines = [ln.strip() for ln in tables[table.split(".")[1]].splitlines()]
        out[fname] = [ln.split()[0] for ln in lines if ln and not ln.startswith("--")]
    return out


def running() -> bool:
    return JOB.get("status") == "running"


def status() -> dict:
    return json.loads(json.dumps(JOB))    # a copy: the worker thread keeps writing to JOB


def samples() -> list[dict]:
    out = []
    if DATA.is_dir():
        for d in sorted(p for p in DATA.iterdir() if p.is_dir()):
            mf = d / "manifest.json"
            if mf.exists() and all((d / f).exists() for f, _ in pipeline.LOADS):
                man = json.loads(mf.read_text(encoding="utf-8"))
                out.append({"id": d.name, "rows": man.get("rows"), "folder": str(d.relative_to(ROOT)),
                            "bytes": sum((d / f).stat().st_size for f, _ in pipeline.LOADS)})
    return sorted(out, key=lambda s: s["rows"] or 0)


def schemas(C) -> list[str]:
    """Schemas (other than RAW) holding all four tables with every required column."""
    need = {t.split(".")[1]: set(file_columns()[f]) for f, t in pipeline.LOADS}
    rows = C.execute("SELECT COLUMN_SCHEMA, COLUMN_TABLE, COLUMN_NAME FROM EXA_ALL_COLUMNS "
                     "WHERE COLUMN_SCHEMA <> 'RAW'").fetchall()
    seen: dict = {}
    for s, t, c in rows:
        if t in need:
            seen.setdefault(s, {}).setdefault(t, set()).add(c)
    return sorted(s for s, tbl in seen.items() if s != pipeline.STAGE and all(need[t] <= tbl.get(t, set()) for t in need))


def dataset(C) -> dict | None:
    """What is loaded now. Data from before this page existed has no name; pipeline.py only loads synthetic manifests."""
    try:
        got = dict(C.execute('SELECT "PARAM_NAME", "PARAM_VALUE" FROM "RECON"."SETTINGS" WHERE "PARAM_NAME" IN '
                             "('dataset_name', 'dataset_source', 'as_of')").fetchall())
        rows = C.execute('SELECT COUNT(*) FROM "RAW"."SWITCH_LOG"').fetchval()
    except pyexasol.ExaError:
        return None
    if not rows:
        return None
    return {"name": got.get("dataset_name", SAMPLE_NAME), "source": got.get("dataset_source", "sample"),
            "rows": rows, "as_of": got.get("as_of")}


def connection() -> dict:
    """The page's opening state. Never raises: a database that is down is what this page exists to fix."""
    out = {"dsn": os.environ.get("EXA_DSN", ""), "user": os.environ.get("EXA_USER", ""), "connected": False, "version": None,
           "error": None, "dataset": None, "schemas": [], "samples": samples(), "files": file_columns(), "job": status()}
    try:
        C = pipeline.connect()
    except (pyexasol.ExaError, KeyError, OSError) as e:
        out["error"] = _why(e)
        return out
    try:
        out.update(connected=True, version=_version(C), schemas=schemas(C), dataset=None if running() else dataset(C))
    finally:
        C.close()
    return out


def _version(C) -> str:
    return C.execute("SELECT PARAM_VALUE FROM EXA_METADATA WHERE PARAM_NAME = 'databaseProductVersion'").fetchval()


def _why(e: BaseException) -> str:
    # pyexasol wraps a failed import in a group of sub-exceptions; the database's own reason is the useful one
    while getattr(e, "exceptions", None):
        e = next((x for x in e.exceptions if isinstance(x, pyexasol.ExaError)), e.exceptions[0])
    text = getattr(e, "message", None) or str(e)
    text = " ".join(str(text).split())
    return (text[:600] + "…" if len(text) > 600 else text) or type(e).__name__


def connect_to(body: dict, on_switch) -> dict:
    """Test a connection and, with use=true, make it the app's database until the server stops."""
    if running():
        raise ValueError("An import is running. Wait for it to finish.")
    dsn = str(body.get("dsn") or "").strip()
    user = str(body.get("user") or "").strip()
    pwd = str(body.get("password") or "")
    if not dsn or not user:
        raise ValueError("Enter the DSN and the user.")
    if not pwd:   # blank keeps the saved password, but only for the login it belongs to
        if (dsn, user) != (os.environ.get("EXA_DSN"), os.environ.get("EXA_USER")):
            raise ValueError("Enter the password for this connection.")
        pwd = os.environ["EXA_PASSWORD"]
    try:
        C = pipeline.connect(user=user, password=pwd, dsn=dsn)
    except (pyexasol.ExaError, OSError) as e:
        raise ValueError(f"Could not connect: {_why(e)}") from e
    try:
        out = {"version": _version(C), "schemas": schemas(C)}
    finally:
        C.close()
    if body.get("use"):
        changed = (dsn, user) != (os.environ.get("EXA_DSN"), os.environ.get("EXA_USER"))
        os.environ.update(EXA_DSN=dsn, EXA_USER=user, EXA_PASSWORD=pwd)
        SWITCHED["reader_needed"] = SWITCHED["reader_needed"] or changed
        on_switch()
    return out


def check_header(path: pathlib.Path, wanted: list[str]) -> str | None:
    """None if the first line is the required header (any case, any order is refused: IMPORT maps by position)."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        head = next(csv.reader(fh), [])
    got = [c.strip().upper() for c in head]
    if got == wanted:
        return None
    return f"Expected the columns {', '.join(wanted)}. This file has {', '.join(got[:12]) or 'no header'}."


def save_upload(upload_id: str, name: str, stream, length: int) -> dict:
    wanted = file_columns().get(name)
    if wanted is None:
        raise ValueError("Unknown file slot.")
    if running():
        raise ValueError("An import is running. Wait for it to finish.")
    upload_id = upload_id or secrets.token_hex(8)
    if not UPLOAD_ID.match(upload_id):
        raise ValueError("Bad upload id.")
    folder = UPLOADS / upload_id
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    left = length
    with open(target, "wb") as fh:
        while left > 0:
            chunk = stream.read(min(CHUNK, left))
            if not chunk:
                break
            fh.write(chunk)
            left -= len(chunk)
    if left:
        target.unlink(missing_ok=True)
        raise ValueError("The upload stopped before the whole file arrived.")
    try:
        problem = check_header(target, wanted)
    except UnicodeDecodeError:
        problem = "This file is not UTF-8 text."
    if problem:
        target.unlink(missing_ok=True)
        raise ValueError(problem)
    return {"upload_id": upload_id, "file": name, "bytes": length}


def _spec(body: dict) -> dict:
    """Validate a request into what the worker needs. Raises ValueError with text the page can show."""
    source, as_of = body.get("source"), str(body.get("as_of") or "").strip().replace("T", " ")
    if as_of and not AS_OF.match(as_of):
        raise ValueError("Cut-off must look like 2026-10-08 06:00.")
    if len(as_of) == 16:
        as_of += ":00"
    name = str(body.get("name") or "").strip()[:60]
    if source == "sample":
        pick = next((s for s in samples() if s["id"] == body.get("dataset")), None)
        if pick is None:
            raise ValueError("Pick a sample dataset.")
        man = json.loads((DATA / pick["id"] / "manifest.json").read_text(encoding="utf-8"))
        return {"source": source, "data": DATA / pick["id"], "scale": str(man["rows"]),
                "manifest": {**man, "name": SAMPLE_NAME, "source": "sample"}}
    if source not in ("upload", "schema"):
        raise ValueError("Pick where the data comes from.")
    if not body.get("confirm_public"):
        raise ValueError("Confirm that this is public or synthetic data.")
    man = {"synthetic": True, "as_of": as_of or None, "source": source}
    if source == "upload":
        upload_id = str(body.get("upload_id") or "")
        if not UPLOAD_ID.match(upload_id):
            raise ValueError("Upload all four files first.")
        folder = UPLOADS / upload_id
        missing = [f for f, _ in pipeline.LOADS if not (folder / f).exists()]
        if missing:
            raise ValueError(f"Still missing: {', '.join(missing)}.")
        return {"source": source, "data": folder, "scale": "upload", "manifest": {**man, "name": name or "Uploaded files"}}
    schema = str(body.get("schema") or "")
    C = pipeline.connect()
    try:
        allowed = schemas(C)
    finally:
        C.close()
    if schema not in allowed:
        raise ValueError("Pick a schema that holds all four tables.")
    return {"source": source, "schema": schema, "scale": "schema", "manifest": {**man, "name": name or f"Exasol schema {schema}"}}


def start(body: dict) -> dict:
    spec = _spec(body)
    reset = bool(body.get("reset_audit", True))
    plan = ["schemas", *(f"load {t}" for _, t in pipeline.LOADS), "settings", *(f"recon {f}" for f in pipeline.RECON_STEPS)]
    if spec["source"] != "sample":    # a sample dataset is known good; anything else proves itself before the old data goes
        plan.insert(0, CHECK_STEP)
    if SWITCHED["reader_needed"]:
        plan.append(READER_STEP)
    with LOCK:
        if running():
            raise ValueError("An import is already running.")
        JOB.clear()
        JOB.update(status="running", id=uuid.uuid4().hex[:12], source=spec["source"], name=spec["manifest"]["name"], error=None,
                   summary=None, started=time.time(), elapsed_s=None,
                   steps=[{"name": n, "state": "waiting", "ms": None, "rows": None} for n in plan])
    threading.Thread(target=_work, args=(spec, reset, plan), daemon=True, name="import").start()
    return status()


def _mark(name: str, state: str, ms=None, rows=None):
    for s in JOB["steps"]:
        if s["name"] == name:
            s.update(state=state, ms=ms, rows=rows)


def _work(spec: dict, reset: bool, plan: list[str]):
    C = T = None
    try:
        C = pipeline.connect()
        T = pipeline.Timer(C, JOB["id"], spec["scale"], on_step=_mark)
        if spec["source"] == "sample":
            pipeline.cmd_load(C, T, spec["data"], reset, manifest=spec["manifest"])
        else:
            T.step(CHECK_STEP, lambda: pipeline.stage(C, spec.get("data"), spec.get("schema")))
            pipeline.cmd_load_schema(C, T, pipeline.STAGE, spec["manifest"], reset)
        pipeline.cmd_recon(C, T)
        if READER_STEP in plan:    # another database has no read-only user yet, and the pages read as that user
            T.step(READER_STEP, setup_agent_user.main)
            SWITCHED["reader_needed"] = False
        JOB["summary"] = {"transactions": C.execute('SELECT COUNT(*) FROM "RAW"."SWITCH_LOG"').fetchval(),
                          "exceptions": C.execute('SELECT COUNT(*) FROM "RECON"."EXCEPTIONS"').fetchval(),
                          "queue": C.execute('SELECT COUNT(*) FROM "RECON"."WORK_QUEUE"').fetchval()}
        JOB["status"] = "done"
    except (Exception, SystemExit) as e:   # pipeline.py stops with SystemExit on a bad dataset
        for s in JOB["steps"]:
            if s["state"] == "running":
                s["state"] = "failed"
        JOB.update(status="failed", error=_why(e))
    finally:
        JOB["elapsed_s"] = round(time.time() - JOB["started"], 1)
        try:
            if T:
                T.flush()
        except Exception as e:    # a failed run must still report its real error
            print(f"timings not saved: {e}")
        if C:
            try:
                pipeline.drop_stage(C)
            except Exception as e:
                print(f"stage not dropped: {e}")
            C.close()
        if spec["source"] == "upload":
            shutil.rmtree(spec["data"], ignore_errors=True)
