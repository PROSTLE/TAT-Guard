"""Who is using the page: server-side sessions, two demo identities, and rate limits.

Each person signs in under their own name and works as an analyst, who proposes, or an approver, who decides. The server
holds the name and role, so the page cannot claim to be someone else, and the proposer can never approve their own
proposal: a second person has to. Who is working right now is shown to everyone.

Public mode (TATGUARD_ACCESS_CODE set) needs the code to open a session. Without it the page is local, and a session opens
on first use. Sessions live in memory: a restart signs everyone out, which suits a demo. This is not a bank's login.
"""
from __future__ import annotations

import collections
import re
import hmac
import secrets
import threading
import time

COOKIE = "tg_session"
SESSION_TTL_S = 12 * 3600      # DESIGN: long enough for a judging day
ROLES = {"analyst": "Reconciliation analyst", "approver": "Operations approver"}
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z .'-]{0,39}$")
ONLINE_S = 60                  # DESIGN: someone counts as here if their page polled within this long


def clean_name(value) -> str:
    name = " ".join(str(value or "").split())
    if not NAME_RE.match(name):
        raise ValueError("Your name: letters, spaces, dots, hyphens and apostrophes, up to 40 characters.")
    return name


def clean_role(value) -> str:
    role = str(value or "analyst")
    if role not in ROLES:
        raise ValueError("unknown role")
    return role


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

    def open(self, role: str = "analyst", name: str = "") -> tuple[str, dict]:
        token = secrets.token_urlsafe(32)
        sess = {"tag": secrets.token_hex(4), "role": role, "name": name, "created": time.time(), "seen": time.time(), "history": []}
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
            if sess:
                sess["seen"] = time.time()
            return sess

    def online(self) -> list[dict]:
        """Everyone signed in whose page is open, by name, so a jury sees who else is working."""
        now, people = time.time(), {}
        with self.lock:
            for s in self.items.values():
                if s.get("name") and now - s["seen"] < ONLINE_S:
                    people[s["name"].casefold()] = {"name": s["name"], "role": s["role"]}
        return sorted(people.values(), key=lambda p: (p["role"], p["name"].casefold()))

    def close(self, token: str | None):
        with self.lock:
            self.items.pop(token or "", None)


def persona(sess: dict) -> dict:
    return {"role": sess["role"], "name": sess.get("name") or "", "title": ROLES[sess["role"]]}


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
