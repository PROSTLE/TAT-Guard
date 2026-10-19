"""TAT Guard UI backend: a single-page app + JSON API (Python standard library only).

    python ui/server.py            # http://127.0.0.1:8765   (env: see docs/SETUP.md; .env is read if present)

* Read endpoints use the read-only agent DB user (TATGUARD_AGENT_USER); their SQL lives in ui/api.py.
  The agent's own SQL goes through the official Exasol MCP server (agent/mcp_reader.py).
* Only /api/propose and /api/actions/<id>/approve|reject write, through agent/actions.py on the admin connection.
* Every number on the page comes from a live query; responses carry the measured query time (ms).
* /api/meta serves the vocabulary the page builds menus from (states, sorts, page sizes, action types and statuses,
  sample questions), so app.js holds only labels and colours.
* Binds to 127.0.0.1 only. There is no login: the approver types a name, which goes into the audit log. That is
  a demo limitation, documented in README "Limitations".
"""
from __future__ import annotations

import json
import mimetypes
import os
import pathlib
import re
import sys
import threading
import time
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_dotenv(path: pathlib.Path):
    """Read KEY=VALUE lines from a git-ignored .env without overriding variables already set."""
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_dotenv(ROOT / ".env")

import pyexasol  # noqa: E402

from agent import actions  # noqa: E402
from agent.agent import SUGGESTIONS, Agent  # noqa: E402
from agent.mcp_reader import McpReader  # noqa: E402
from recon.pipeline import connect as admin_connect, host_label  # noqa: E402
from ui import api  # noqa: E402

HOST, PORT = "127.0.0.1", int(os.environ.get("TATGUARD_UI_PORT", "8765"))
MAX_BODY = 64 * 1024
STATIC = ROOT / "ui" / "static"
ACTION_ID = re.compile(r"^PA-[0-9A-F]{12}$")
# Binding to 127.0.0.1 does not stop a web page in the user's browser from calling this server. Requests must name
# this server in Host (blocks DNS rebinding), carry no foreign Origin, and POSTs must be application/json (a
# cross-site form cannot send that without a CORS preflight, which this server never answers).
LOCAL_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}


class Db:
    """One lock-protected connection with reconnect-on-failure."""

    def __init__(self, factory):
        self.factory, self.C, self.lock = factory, None, threading.Lock()

    def run(self, fn):
        with self.lock:
            for attempt in (1, 2):
                try:
                    if self.C is None or self.C.is_closed:
                        self.C = self.factory()
                    return fn(self.C)
                except (pyexasol.ExaCommunicationError, pyexasol.ExaConnectionError):
                    self.C = None
                    if attempt == 2:
                        raise


def _reader_conn():
    # same DSN/TLS handling (EXA_ENCRYPTION) as the admin connection, but as the read-only user
    return admin_connect(user=os.environ.get("TATGUARD_AGENT_USER", "TATGUARD_AGENT"),
                         password=os.environ["TATGUARD_AGENT_PASSWORD"])


READ, WRITE = Db(_reader_conn), Db(admin_connect)
AGENT: dict = {"agent": None, "error": None}


def start_agent():
    try:
        reader = McpReader()
        AGENT["agent"] = Agent(reader, propose_fn=lambda t, r, why, ev: WRITE.run(
            lambda C: actions.propose(C, t, r, why, ev, created_by="agent:" + AGENT["agent"].mode)),
            action_types=actions.ACTION_TYPES)
    except Exception as e:
        AGENT["error"] = f"{type(e).__name__}: {e}"


def q(sql: str, params: dict | None = None) -> dict:
    """Read query on the read-only connection; returns columns, rows (JSON-safe) and measured ms."""
    def run(C):
        t0 = time.perf_counter()
        st = C.execute(sql, params or {})
        cols = st.column_names()
        rows = [[None if v is None else (v if isinstance(v, (int, float, str)) else str(v)) for v in r] for r in st]
        return {"columns": cols, "rows": rows, "ms": round((time.perf_counter() - t0) * 1000)}
    return READ.run(run)


def first(qs: dict) -> dict:
    return {k: v[0] for k, v in qs.items() if v}


# ------------------------------------------------------------------ endpoints
def api_health(_):
    h = api.health(q)
    a = AGENT["agent"]
    return {**h, "host_label": host_label(), "agent_mode": a.mode if a else None, "agent_error": AGENT["error"],
            "agent_ready": a is not None}


def api_ask(body):
    if AGENT["agent"] is None:
        return {"error": AGENT["error"] or "The assistant is starting (the MCP server takes a few seconds)."}, \
            HTTPStatus.SERVICE_UNAVAILABLE
    t0 = time.perf_counter()
    out = AGENT["agent"].ask(body.get("question", ""))
    out["total_ms"] = round((time.perf_counter() - t0) * 1000)
    for r in out.get("queries", []):
        r["row_count"] = len(r["rows"])
        r["rows"] = r["rows"][:25]
    return out


def api_propose(body):
    user = str(body.get("user") or "").strip()
    if not user:
        raise ValueError("Set your name (top right) before proposing an action.")
    targets = body.get("targets") or [body.get("target_ref", "")]
    if not isinstance(targets, list) or not 1 <= len(targets) <= 50:
        raise ValueError("between 1 and 50 targets per request")
    results = []
    for t in targets:
        try:
            r = WRITE.run(lambda C, t=t: actions.propose(C, body.get("action_type", ""), str(t),
                                                         body.get("rationale") or "Proposed from the work queue", "",
                                                         created_by="analyst:" + user[:80]))
            results.append({"target_ref": t, **r})
        except actions.ActionError as e:
            results.append({"target_ref": t, "error": str(e)})
    return {"resu