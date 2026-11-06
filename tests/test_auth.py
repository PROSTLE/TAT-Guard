"""Offline tests for ui/auth.py and for what public mode refuses to serve."""
import time

import pytest

from agent import actions
from ui import auth, server


def test_limiter_blocks_past_the_limit_and_recovers():
    lim = auth.Limiter()
    assert [lim.allow("k", 2, 60) for _ in range(3)] == [True, True, False]
    assert lim.allow("other", 2, 60)
    lim.hits["k"][0] -= 61
    assert lim.allow("k", 2, 60)


def test_only_the_right_code_passes():
    s = auth.Sessions("secret-code")
    assert s.public and s.code_ok("secret-code")
    assert not s.code_ok("secret-cod") and not s.code_ok("") and not s.code_ok(None)


def test_no_code_means_local_use():
    assert not auth.Sessions("").public


def test_sessions_open_close_and_expire():
    s = auth.Sessions("x")
    token, sess = s.open("approver", "Arjun")
    assert s.get(token) is sess and sess["role"] == "approver" and sess["name"] == "Arjun" and s.get("nope") is None and s.get(None) is None
    sess["created"] = time.time() - auth.SESSION_TTL_S - 1
    assert s.get(token) is None
    token, _ = s.open()
    s.close(token)
    assert s.get(token) is None


def test_session_tokens_are_long_and_unique():
    s = auth.Sessions("x")
    a, b = s.open()[0], s.open()[0]
    assert a != b and len(a) >= 40


def test_cookie_round_trip():
    header = auth.set_cookie("abc", secure=True)
    assert "HttpOnly" in header and "Secure" in header and "SameSite=Lax" in header
    assert "Secure" not in auth.set_cookie("abc", secure=False)
    assert auth.cookie_from("a=1; tg_session=abc; b=2") == "abc"
    assert auth.cookie_from("a=1") is None and auth.cookie_from(None) is None


def test_two_people_are_two_people_to_maker_checker():
    assert not actions.same_person(actions.ANALYST_PREFIX + "Priya Nair", "Arjun Mehta")
    assert actions.same_person(actions.ANALYST_PREFIX + "Priya Nair", " priya nair ")


@pytest.mark.parametrize("bad", ["", " ", "<b>x</b>", "1Priya", "a" * 41, "x'); DROP", None])
def test_bad_names_are_refused(bad):
    with pytest.raises(ValueError):
        auth.clean_name(bad)


def test_names_are_tidied_and_roles_checked():
    assert auth.clean_name("  Priya   Nair ") == "Priya Nair"
    assert auth.clean_role("approver") == "approver"
    with pytest.raises(ValueError):
        auth.clean_role("admin")


def test_online_lists_named_people_seen_recently_once_each():
    s = auth.Sessions("x")
    s.open("analyst", "Priya")
    s.open("approver", "Arjun")
    s.open("analyst", "priya")      # the same person in a second tab
    _, ghost = s.open("analyst", "Old")
    ghost["seen"] -= auth.ONLINE_S + 1
    s.open("analyst", "")
    assert [p["name"] for p in s.online()] == ["Priya", "Arjun"] or [p["name"] for p in s.online()] == ["priya", "Arjun"]


def test_routes_that_change_the_database_are_local_only():
    assert {"/api/connect", "/api/import", "/api/upload", "/api/live/reset"} <= server.LOCAL_ONLY
    assert server.OPEN_ROUTES == {"/api/session", "/api/meta"}


def test_csp_allows_no_inline_script_or_other_origin():
    assert "script-src 'self';" in server.CSP and "frame-ancestors 'none'" in server.CSP


def test_each_action_has_its_own_allowance(monkeypatch):
    monkeypatch.setattr(server, "LIMITER", auth.Limiter())
    server.limited("visitor", "pay")
    server.limited("visitor", "storm")
    server.limited("visitor", "late_file")    # refused before the limiter kept one bucket per action
    server.limited("visitor", "late_file")
    with pytest.raises(ValueError):
        server.limited("visitor", "late_file")
