"""Offline contract between ui/static/app.js and the backend: the page may only call routes the server serves, and its
label maps must cover every value the backend can send (no database needed)."""
import re

import pytest

from agent import actions
from agent.agent import ROUTES, SUGGESTIONS
from ui import api, server

APP_JS = "\n".join(p.read_text(encoding="utf-8") for p in sorted((api.ROOT / "ui" / "static").glob("*.js")))
CSV_ROUTES = set(server.CSV_ROUTES)
# Served for scripts on a local install only, with no page: the database switch and bulk import. Never served in public mode.
NO_PAGE = {"/api/connection", "/api/imports", "/api/connect", "/api/import", "/api/upload", "/api/live/reset"}
SERVED = set(server.GET_ROUTES) | set(server.SESSION_GET_ROUTES) | set(server.POST_ROUTES) | CSV_ROUTES | {"/api/session", "/api/actions"}


def js_map_keys(name: str) -> set:
    block = re.search(r"const " + name + r" = \{(.*?)\n\};", APP_JS, re.S)
    assert block, f"{name} not found in the page's scripts"
    return set(re.findall(r"^\s*([A-Z][A-Z0-9_]+):|, ([A-Z][A-Z0-9_]+):", block.group(1), re.M)[i][j]
               for i in range(len(re.findall(r"^\s*([A-Z][A-Z0-9_]+):|, ([A-Z][A-Z0-9_]+):", block.group(1), re.M))) for j in (0, 1)) - {""}


def test_page_calls_only_served_routes_and_every_route_is_used():
    called = {c.rstrip("/") for c in re.findall(r"/api/[a-z./-]+", APP_JS)}
    assert called <= SERVED, f"page calls routes the server does not serve: {called - SERVED}"
    assert SERVED - NO_PAGE <= called, f"server routes the page never calls: {SERVED - NO_PAGE - called}"


def test_local_only_routes_are_refused_in_public_mode():
    assert NO_PAGE == server.LOCAL_ONLY


def test_label_maps_cover_every_backend_value():
    classify = (api.ROOT / "sql" / "15_classify.sql").read_text(encoding="utf-8")
    class_case = re.search(r"CASE(.*?)END AS \"CLASS\"", classify, re.S).group(1)
    classes = set(re.findall(r"THEN '([A-Z_]+)'", class_case)) | {"UNMATCHED_CBS_DEBIT"}   # + the orphan-debit branch
    assert len(classes) == 7
    assert classes <= js_map_keys("CLASS_META")
    assert set(api.TAT_STATES) <= js_map_keys("STATE_META")
    assert set(actions.ACTION_TYPES) <= js_map_keys("ACTION_META")
    assert set(actions.STATUSES) <= js_map_keys("STATUS_TONE")
    view = (api.ROOT / "sql" / "30_penalty_view.sql").read_text(encoding="utf-8")
    comp = re.search(r"CASE WHEN d\.\"PENALTY_DAYS\" = 0 THEN(.*?)END AS \"COMP_STATUS\"", view, re.S).group(0)
    assert set(re.findall(r"(?:THEN|ELSE) '([A-Z_]+)'", comp)) == js_map_keys("COMP_META")


def test_meta_serves_the_backend_vocabulary():
    m = server.api_meta({})
    assert m["tat_states"] == list(api.TAT_STATES) and m["queue_sorts"] == list(api.QUEUE_SORT)
    assert m["default_page_size"] in m["page_sizes"] and m["action_statuses"] == list(actions.STATUSES)
    assert m["queue_focus"] == list(api.QUEUE_FOCUS) and m["maker_checker"] == actions.MAKER_CHECKER
    assert set(m["action_types"]) == set(actions.ACTION_TYPES) and m["suggestions"] == SUGGESTIONS


def test_row_actions_are_real_action_types_and_reach_the_queue():
    assert set(actions.PROPOSE_WHEN) <= set(actions.ACTION_TYPES)
    assert '"PROPOSE_ACTION"' in api.QUEUE_COLS
    for a, cond in actions.PROPOSE_WHEN.items():
        assert f"WHEN {cond} THEN '{a}'" in api.PROPOSE_ACTION_SQL


@pytest.mark.parametrize("question", SUGGESTIONS)
def test_every_suggested_question_reaches_a_playbook(question):
    assert any(p.search(question) for p, _ in ROUTES), f"{question!r} has no deterministic route"


def test_sources_counts_every_loaded_table():
    sent = []

    def q(sql, params=None):
        sent.append(sql)
        return {"columns": ["TBL", "N"], "rows": [], "ms": 0}
    api.sources(q)
    for _, table in api.LOADS:
        s, n = table.split(".")
        assert f'FROM "{s}"."{n}"' in sent[0]
