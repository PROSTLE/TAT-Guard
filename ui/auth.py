"""Who is using the page: server-side sessions, two demo identities, and rate limits.

Maker-checker only means something if the server decides who you are, so identity is not typed into the page any more.
A session is either the analyst, who can propose, or the approver, who can decide; the same visitor can switch between
them to walk a case end to end, and the proposer can still never approve their own proposal.

Public mode (TATGUARD_ACCESS_CODE set) needs the code to open a session. Without it the page is local, and a session opens
on first use. Sessions live in memory: a restart signs everyone out, which suits a demo. This is not a bank's login.
"""
from __future__ import annotations

import collections
import hmac
import secrets
import threading
import time

COOKIE = "tg_session"
SESSION_TTL_S = 12 * 3600      # DESIGN: long enough for a judging day
PERSONAS = {   # fictional people
    "analyst": {"name": "Asha Rao", "title": "Reconciliation analyst"},
    "approver": {"name": "Vikram Shah", "title": "Operations approver"},
}


class Limiter:
    """Sliding-window counters by key. In memory: limits protect the demo, they are not a billing record."""

    def __init__(self):
        self.hits, self.lock = collections.defaultdict(collections.deque), threading.Lock()

    def allow(self, key: str, limit: int, window_s: int) -> bool:
        now = time.time()
        with self.lock:
            q = self.hits[key]
            while q and q[0] <= now - window_s:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True


class Sessions:
    def __init__(self, access_code: str = ""):
        self.code, self.items, self.lock = access_code, {}, threading.Lock()

    @property
    def public(self) -> bool:
        return bool(self.code)

    def code_ok(self, code: str) -> bool:
        return hmac.compare_digest(str(code or "").encode(), self.code.encode())

    def open(self, role: str = "analyst") -> tuple[str, dict]:
        token = secrets.token_urlsafe(32)
        sess = {"tag": secrets.token_hex(4), "role": role, "created": time.time(), "history": []}
        with self.lock:
            self.items = {k: v for k, v in self.items.items() if time.time() - v["created"] < SESSION_TTL_S}
            self.items[token] = sess
        return token, sess

    def get(self, token: str | None) -> dict | None:
        with self.lock:
            sess = self.items.get(token or "")
            if sess and time.time() - sess["created"] >= SESSION_TTL_S:
                del self.items[token]
                return None
            return sess

    def close(self, token: str | None):
        with self.lock:
            self.items.pop(token or "", None)


def persona(sess: dict) -> dict:
    return {"role": sess["role"], **PERSONAS[sess["role"]]}


def cookie_from(header: str | None) -> str | None:
    for part in (header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE:
            return v
    return None


def set_cookie(token: str, secure: bool) -> str:
    return f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_TTL_S}" + ("; Secure" if secure else "")


def clear_cookie() -> str:
    return f"{COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
