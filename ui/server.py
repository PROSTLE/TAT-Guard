"""TAT Guard UI backend: a single-page app + JSON API (Python standard library only).

    python ui/server.py            # http://127.0.0.1:8765   (env: see docs/SETUP.md; .env is read if present)

* Read endpoints use the read-only agent DB user (TATGUARD_AGENT_USER); their SQL lives in ui/api.py.
  The agent's own SQL goes through the official Exasol MCP server (agent/mcp_reader.py).
* /api/propose and /api/actions/<id>/approve|reject write through agent/actions.py on the admin connection.
* /api/connect, /api/upload and /api/import are the Connect & Import page (ui/importer.py): they choose the database,
  and replace the data in it through recon/pipeline.py. Pages cannot change data while an import runs.
* Every number on the page comes from a live query; responses carry the measured query time (ms).
* /api/meta serves the vocabulary the page builds menus from (states, sorts, page sizes, action types and statuses,
  sample questions, maker-checker setting), so app.js holds only labels and colours.
* The Live page's writes go through ui/live.py, one job at a time. Identity comes from a server-side session (ui/auth.py).
* Binds to 127.0.0.1 only. Set TATGUARD_ACCESS_CODE and TATGUARD_PUBLIC_HOST to put a tunnel in front of it: the code
  gates every API call, rate limits apply, and the routes that can change the database connection or replace the
  data are not served at all.
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
import uuid
from concurrent.futures import ThreadPoolExecutor
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
from ui import api, auth, importer, live  # noqa: E402

HOST, PORT = "127.0.0.1", int(os.environ.get("TATGUARD_UI_PORT", "8765"))
MAX_BODY = 64 * 1024
SESSIONS = auth.Sessions(os.environ.get("TATGUARD_ACCESS_CODE", ""))
LIMITER = auth.Limiter()
# Public hosts this server may be reached under: exact names, or ".example.com" for any host under that domain
PUBLIC_HOSTS = [h.strip().lower() for h in os.environ.get("TATGUARD_PUBLIC_HOST", "").split(",") if h.strip()]
IDLE_RESET_S = int(os.environ.get("TATGUARD_IDLE_RESET_MIN", "30")) * 60 if SESSIONS.public else 0
# What one visitor (or, for "*_all", everyone together) can do. DESIGN: enough to explore, not enough to run up a bill.
LIMITS = {"pay": (12, 60), "storm": (2, 60), "storm_all": (6, 3600), "clock": (10, 60), "late_file": (2, 60), "ask": (8, 60),
          "ask_all": (150, 86400), "propose": (30, 60), "decide": (20, 60), "login": (12, 60)}
LOCAL_ONLY = {"/api/connection", "/api/imports", "/api/connect", "/api/import", "/api/upload", "/api/live/reset"}
OPEN_ROUTES = {"/api/session", "/api/meta"}     # everything else under /api/ needs a session
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; font-src 'self'; connect-src 'self'; "
       "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
ASK_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ask")
ASK_JOBS: dict = {}
MAX_ASK_JOBS = 200
HISTORY_TURNS = 6          # DESIGN: earlier questions the model sees, so a follow-up can say "that bank"
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

    def reset(self):
        """Log out, so the next call opens a connection from the current environment."""
        with self.lock:
            if self.C is not None and not self.C.is_closed:
                self.C.close()
            self.C = None

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


READ, WRITE, FAST = Db(_reader_conn), Db(admin_connect), Db(admin_connect)   # WRITE is held for whole reconciliations
AGENT: dict = {"agent": None, "error": None}
ENGINE: dict = {"live": None}


def engine() -> live.Engine:
    return ENGINE["live"]


def start_agent():
    try:
        reader = McpReader()
        AGENT["agent"] = Agent(reader, propose_fn=lambda t, r, why, ev: FAST.run(
            lambda C: actions.propose(C, t, r, why, ev, created_by="agent:" + AGENT["agent"].mode)),
            action_types=actions.ACTION_TYPES)
    except Exception as e:
        AGENT["error"] = f"{type(e).__name__}: {e}"


def switch_database():
    """Called after the page picks another database: nothing may keep talking to the old one."""
    READ.reset()
    WRITE.reset()
    FAST.reset()
    old, AGENT["agent"], AGENT["error"] = AGENT["agent"], None, None
    if old:
        old.reader.close()
    threading.Thread(target=start_agent, daemon=True, name="agent-start").start()


def no_import_running():
    if importer.running():
        raise ValueError("An import is running. Wait for it to finish.")


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


def limited(key: str, name: str):
    lim, win = LIMITS[name]
    if not LIMITER.allow(f"{name}:{key}", lim, win):      # one bucket per action, so a payment does not use up the outage allowance
        raise ValueError("That is a lot at once for a shared demo. Give it a minute and try again.")


def need_role(sess: dict, role: str):
    if sess["role"] != role:
        who = auth.PERSONAS[role]
        raise ValueError(f"Switch to {who['name']} ({who['title'].lower()}) at the top right to do this.")


def run_ask(job, question, sess):
    agent = AGENT["agent"]

    def on_step(step):
        job["steps"].append(step)
        if step.get("kind") == "sql":
            is_model = agent.mode == "gemini"
            engine().log("AI analyst" if is_model else "System", "Query written by the model" if is_model else "Prepared query",
                         live.plain_sql(step["sql"]), step.get("ms"), step.get("rows"), tone="bad" if step.get("error") else "")
    t0 = time.perf_counter()
    try:
        out = agent.ask(question, history=list(sess["history"]), on_step=on_step)
        out["total_ms"] = round((time.perf_counter() - t0) * 1000)
        for r in out.get("queries", []):
            r["row_count"] = len(r["rows"])
            r["rows"] = r["rows"][:25]
        sess["history"] = (sess["history"] + [{"q": question, "a": out.get("answer", "")}])[-HISTORY_TURNS:]
        job.update(state="done", result=out)
    except Exception as e:
        traceback.print_exc()
        job.update(state="failed", error=f"{type(e).__name__}: {e}"[:300])


def api_ask(body, sess):
    no_import_running()
    if AGENT["agent"] is None:
        return {"error": AGENT["error"] or "The assistant is starting (the MCP server takes a few seconds)."}, \
            HTTPStatus.SERVICE_UNAVAILABLE
    limited(sess["tag"], "ask")
    limited("all", "ask_all")
    question = str(body.get("question", "")).strip()[:2000]
    if not question:
        raise ValueError("Ask a question.")
    job = {"id": "A" + uuid.uuid4().hex[:12], "owner": sess["tag"], "state": "running", "question": question, "steps": [], "result": None, "error": None}
    ASK_JOBS[job["id"]] = job
    while len(ASK_JOBS) > MAX_ASK_JOBS:
        ASK_JOBS.pop(next(iter(ASK_JOBS)))
    ASK_POOL.submit(run_ask, job, question, sess)
    return {"id": job["id"]}


def api_ask_status(args, sess):
    job = ASK_JOBS.get(args.get("id", ""))
    if not job or job["owner"] != sess["tag"]:
        raise ValueError("no such question")
    return {k: v for k, v in job.items() if k != "owner"}


def api_propose(body, sess):
    no_import_running()
    need_role(sess, "analyst")
    limited(sess["tag"], "propose")
    user = auth.PERSONAS[sess["role"]]["name"]
    targets = body.get("targets") or [body.get("target_ref", "")]
    if not isinstance(targets, list) or not 1 <= len(targets) <= 50:
        raise ValueError("between 1 and 50 targets per request")
    results = []
    for t in targets:
        try:
            r = FAST.run(lambda C, t=t: actions.propose(C, body.get("action_type", ""), str(t),
                                                        body.get("rationale") or "Proposed from the work queue", "",
                                                        created_by=actions.ANALYST_PREFIX + user))
            results.append({"target_ref": t, **r})
        except actions.ActionError as e:
            results.append({"target_ref": t, "error": str(e)})
    return {"results": results}


def api_decide(action_id, approve, sess):
    if not ACTION_ID.match(action_id):
        raise ValueError("bad action id")
    no_import_running()
    need_role(sess, "approver")
    limited(sess["tag"], "decide")
    return engine().decide(sess["tag"], action_id, approve, auth.PERSONAS[sess["role"]]["name"])


def api_pay(body, sess):
    no_import_running()
    limited(sess["tag"], "pay")
    return engine().pay(sess["tag"], body)


def api_storm(body, sess):
    no_import_running()
    limited(sess["tag"], "storm")
    limited("all", "storm_all")
    return engine().storm(sess["tag"], body)


def api_clock(body, sess):
    no_import_running()
    limited(sess["tag"], "clock")
    try:
        days = int(body.get("days", 1))
    except (TypeError, ValueError):
        raise ValueError("The clock moves 1, 2 or 5 days.") from None
    return engine().move_clock(sess["tag"], days)


def api_late_file(body, sess):
    no_import_running()
    limited(sess["tag"], "late_file")
    return engine().late_file(sess["tag"])


def api_reset(body, sess):
    no_import_running()
    return engine().reset(sess["tag"])


def api_session_view(sess, can_reset: bool = False) -> dict:
    a = AGENT["agent"]
    return {"authenticated": sess is not None, "public": SESSIONS.public, "can_reset": can_reset, "persona": auth.persona(sess) if sess else None,
            "personas": auth.PERSONAS, "ai": {"mode": a.mode if a else None, "ready": a is not None, "error": AGENT["error"]}}


def api_meta(_):
    """Everything the page would otherwise hard-code: allowed values, action types, sample questions."""
    return {**api.vocabulary(), "action_types": actions.ACTION_TYPES, "suggestions": SUGGESTIONS, "live": live.meta(), "public": SESSIONS.public}


GET_ROUTES = {
    "/api/meta": api_meta,
    "/api/health": api_health,
    "/api/overview": lambda a: api.overview(q),
    "/api/queue": lambda a: api.queue(q, a),
    "/api/txn": lambda a: api.transaction_detail(q, a.get("id", "")),
    "/api/actions": lambda a: api.proposals(q, a.get("status", "")),
    "/api/audit": lambda a: api.audit_log(q),
    "/api/sources": lambda a: api.sources(q),
    "/api/reports": lambda a: api.reports_list(),
    "/api/report": lambda a: api.report_text(a.get("name", "")),
    "/api/connection": lambda a: importer.connection(),
    "/api/imports": lambda a: importer.status(),
    "/api/live/verify": lambda a: engine().verify(),
}
SESSION_GET_ROUTES = {       # routes that depend on who is asking
    "/api/live/state": lambda a, s: engine().state(api._int(a.get("since"), 0, 0, 10 ** 12), s["tag"]),
    "/api/ask/status": api_ask_status,
}
POST_ROUTES = {
    "/api/ask": api_ask,
    "/api/propose": api_propose,
    "/api/live/pay": api_pay,
    "/api/live/storm": api_storm,
    "/api/live/clock": api_clock,
    "/api/live/late-file": api_late_file,
    "/api/live/reset": api_reset,
}


CSV_ROUTES = {
    "/api/queue.csv": (lambda a: api.queue_csv(q, a), "tatguard_work_queue.csv"),
    "/api/compensation.csv": (lambda a: api.compensation_csv(q), "tatguard_compensation_register.csv"),
}


class Handler(BaseHTTPRequestHandler):
    server_version = "TATGuard"
    new_cookie, sess, token = None, None, None

    def _send(self, code, payload, ctype="application/json", extra=None):
        data = payload if isinstance(payload, bytes) else (
            payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload, default=str).encode("utf-8"))
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        if self.new_cookie:
            self.send_header("Set-Cookie", self.new_cookie)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _guard(self, fn):
        try:
            res = fn()
            code = HTTPStatus.OK
            if isinstance(res, tuple):
                res, code = res
            self._send(code, res)
        except (ValueError, actions.ActionError) as e:
            self._send(HTTPStatus.BAD_REQUEST, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{type(e).__name__}: {e}"[:500]})

    def _static(self, rel: str):
        p = (STATIC / unquote(rel)).resolve()
        if STATIC.resolve() not in p.parents or not p.is_file():
            return self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "text/javascript"):
            ctype += "; charset=utf-8"
        self._send(HTTPStatus.OK, p.read_bytes(), ctype)

    def _host_ok(self, host: str) -> bool:
        host = host.lower()
        return host in LOCAL_HOSTS or any(host == h or (h.startswith(".") and host.endswith(h)) for h in PUBLIC_HOSTS)

    def _foreign(self) -> bool:
        """True (and a 403 sent) if the request does not come from this server's own page."""
        origin, host = self.headers.get("Origin"), self.headers.get("Host", "")
        if not self._host_ok(host) or (origin and urlparse(origin).netloc.lower() != host.lower()):
            self._send(HTTPStatus.FORBIDDEN, {"error": "request not from the TAT Guard page"})
            return True
        return False

    def _secure(self) -> bool:
        return self.headers.get("X-Forwarded-Proto", "").lower() == "https"

    def _client(self) -> str:
        return self.headers.get("CF-Connecting-IP") or self.client_address[0]

    def _load_session(self):
        self.token = auth.cookie_from(self.headers.get("Cookie"))
        self.sess = SESSIONS.get(self.token)
        if self.sess is None and not SESSIONS.public:     # local use: no code to enter
            self.token, self.sess = SESSIONS.open()
            self.new_cookie = auth.set_cookie(self.token, self._secure())

    def _from_this_machine(self) -> bool:
        """The presenter at the machine itself. A tunnel always adds a forwarded-for header and a public Host."""
        return (self.headers.get("Host", "").lower() in LOCAL_HOSTS and self.client_address[0] == HOST
                and not self.headers.get("CF-Connecting-IP") and not self.headers.get("X-Forwarded-For"))

    def _locked_out(self, path: str) -> bool:
        """True (and the response sent) if this API path is not available to this request."""
        if not path.startswith("/api/"):
            return False
        if SESSIONS.public and path in LOCAL_ONLY and not self._from_this_machine():
            self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return True
        if self.sess is None and path not in OPEN_ROUTES:
            self._send(HTTPStatus.UNAUTHORIZED, {"error": "Sign in first."})
            return True
        return False

    def do_GET(self):
        if self._foreign():
            return
        u = urlparse(self.path)
        args = first(parse_qs(u.query))
        self._load_session()
        if u.path in ("/", "/index.html"):
            return self._send(HTTPStatus.OK, (ROOT / "ui" / "index.html").read_bytes(), "text/html; charset=utf-8")
        if u.path.startswith("/static/"):
            return self._static(u.path[len("/static/"):])
        if self._locked_out(u.path):
            return
        if u.path == "/api/session":
            return self._guard(lambda: api_session_view(self.sess, self._from_this_machine()))
        if u.path in CSV_ROUTES:
            fn, filename = CSV_ROUTES[u.path]
            try:
                body = fn(args)
            except ValueError as e:
                return self._send(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            return self._send(HTTPStatus.OK, body, "text/csv; charset=utf-8",
                              {"Content-Disposition": f'attachment; filename="{filename}"'})
        if u.path in SESSION_GET_ROUTES:
            return self._guard(lambda: SESSION_GET_ROUTES[u.path](args, self.sess))
        if u.path in GET_ROUTES:
            return self._guard(lambda: GET_ROUTES[u.path](args))
        self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def _session_post(self, body):
        """Sign in, switch between the analyst and the approver, or sign out."""
        if body.get("action") == "logout":
            SESSIONS.close(self.token)
            self.new_cookie = auth.clear_cookie()
            self.sess = None
            return api_session_view(None)
        role = str(body.get("role") or "analyst")
        if role not in auth.PERSONAS:
            raise ValueError("unknown role")
        if self.sess is None:
            limited("login:" + self._client(), "login")
            if not SESSIONS.code_ok(body.get("code", "")):
                return {"error": "That access code is not right."}, HTTPStatus.UNAUTHORIZED
            self.token, self.sess = SESSIONS.open(role)
            self.new_cookie = auth.set_cookie(self.token, self._secure())
        self.sess["role"] = role
        return api_session_view(self.sess, self._from_this_machine())

    def do_POST(self):
        if self._foreign():
            return
        ctype = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        self._load_session()
        if self._locked_out(u.path):
            return
        if u.path == "/api/upload" and ctype == "application/octet-stream":   # large file body; a cross-site form cannot send this type
            args = first(parse_qs(u.query))
            return self._guard(lambda: importer.save_upload(args.get("id", ""), args.get("file", ""), self.rfile, n))
        if ctype != "application/json":
            return self._send(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "Content-Type must be application/json"})
        if n > MAX_BODY:
            return self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "body too large"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self._send(HTTPStatus.BAD_REQUEST, {"error": "JSON object expected"})
        if u.path == "/api/session":
            return self._guard(lambda: self._session_post(body))
        m = re.fullmatch(r"/api/actions/([^/]+)/(approve|reject)", u.path)
        if u.path == "/api/connect":
            return self._guard(lambda: importer.connect_to(body, switch_database))
        if u.path == "/api/import":
            return self._guard(lambda: importer.start(body))
        if u.path in POST_ROUTES:
            return self._guard(lambda: POST_ROUTES[u.path](body, self.sess))
        if m:
            return self._guard(lambda: api_decide(m.group(1), m.group(2) == "approve", self.sess))
        self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def log_message(self, fmt, *args):  # one short line per request, except the page's own polling
        if "/api/live/state" not in str(args[0]) and "/api/ask/status" not in str(args[0]):
            sys.stderr.write(f"{self.log_date_time_string()} {fmt % args}\n")


def main():
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    threading.Thread(target=start_agent, daemon=True, name="agent-start").start()
    ENGINE["live"] = live.Engine(WRITE, FAST, q, live.data_dir(), idle_reset_s=IDLE_RESET_S)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"TAT Guard UI on http://{HOST}:{PORT}  (data: SYNTHETIC; {'public, access code required' if SESSIONS.public else 'local'}; "
          f"host label: {host_label()})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if AGENT["agent"]:
            AGENT["agent"].reader.close()


if __name__ == "__main__":
    main()
