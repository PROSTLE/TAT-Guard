"""Offline tests for Gemini mode (no network, no key): a fake client returns scripted responses built from the real
google-genai types, so the tool loop is checked against the installed SDK's data model."""
import pytest
from google.genai import types

from agent import agent as agent_mod

ACTION_TYPES = {"POST_REVERSAL": "reverse", "PAY_COMPENSATION": "pay", "CHASE_SETTLEMENT_FILE": "chase"}


def reply(*parts, finish="STOP", block=None):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)), finish_reason=finish)],
        prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason=block) if block else None)


def call(name, args, cid="c1"):
    return types.Part(function_call=types.FunctionCall(id=cid, name=name, args=args))


class FakeClient:
    def __init__(self, script):
        self.script, self.sent = list(script), []
        self.models = self

    def generate_content(self, *, model, contents, config):
        self.sent.append((model, list(contents), config))
        return self.script.pop(0)


class FakeReader:
    def query(self, sql):
        return {"sql": sql, "columns": ["N"], "rows": [[44807]], "ms": 1}


@pytest.fixture
def run(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("TATGUARD_LLM", raising=False)

    def go(script, question="How many exceptions?"):
        client = FakeClient(script)
        monkeypatch.setattr(agent_mod, "_gemini_client", lambda: client)
        a = agent_mod.Agent(FakeReader(), lambda *x: {"action_id": "PA-1"}, ACTION_TYPES)
        return a.ask(question), client
    return go


def test_mode_is_chosen_by_the_gemini_key_only(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "x")             # only GEMINI_API_KEY switches the mode on
    assert not agent_mod.llm_available()
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert agent_mod.llm_available()
    monkeypatch.setenv("TATGUARD_LLM", "off")
    assert not agent_mod.llm_available()


def test_tool_call_runs_through_run_tool_and_grounded_answer_is_returned(run):
    out, client = run([reply(call("run_sql", {"sql": "SELECT 1"})),
                       reply(types.Part(text="thinking 999", thought=True), types.Part(text="There are 44,807 exceptions."))])
    assert out["mode"] == "gemini" and out["grounded"] and out["answer"] == "There are 44,807 exceptions."
    assert [q["sql"] for q in out["queries"]] == ["SELECT 1"]
    model, contents, config = client.sent[1]
    assert model == agent_mod.MODEL
    resp = contents[-1].parts[0].function_response          # result went back with the call's id, as "output"
    assert contents[-1].role == "user" and resp.id == "c1" and resp.name == "run_sql" and "output" in resp.response
    assert config.automatic_function_calling.disable is True
    assert {f.name for f in config.tools[0].function_declarations} == {"run_sql", "run_playbook", "propose_action"}


def test_tool_error_goes_back_as_error(run):
    out, client = run([reply(call("run_sql", {})), reply(types.Part(text="I don't have that data."))])
    resp = client.sent[1][1][-1].parts[0].function_response
    assert "error" in resp.response and "KeyError" in resp.response["error"]


def test_ungrounded_answer_is_retried_then_replaced(run):
    out, client = run([reply(types.Part(text="We owe Rs 987,654."))] * 3)
    assert out["answer"].startswith("I couldn't summarise") and len(client.sent) == 3
    assert "987654" in client.sent[1][1][-1].parts[0].text      # the model was told which number was ungrounded


@pytest.mark.parametrize("resp", [reply(types.Part(text="no"), finish="SAFETY"),
                                  types.GenerateContentResponse(candidates=[], prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason="SAFETY"))])
def test_declined_requests_are_reported_as_declined(run, resp):
    out, _ = run([resp])
    assert out["answer"] == "The model declined this request."


def test_proposal_id_may_be_quoted(run):
    out, _ = run([reply(call("propose_action", {"action_type": "POST_REVERSAL", "target_ref": "E1", "rationale": "r"})),
                  reply(types.Part(text="Proposed PA-1."))])
    assert out["grounded"] and out["proposal"] == {"action_id": "PA-1"}


def test_earlier_turns_reach_the_model_so_a_follow_up_has_context(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = FakeClient([reply(types.Part(text="Done."))])
    monkeypatch.setattr(agent_mod, "_gemini_client", lambda: client)
    a = agent_mod.Agent(FakeReader(), lambda *x: {}, ACTION_TYPES)
    a.ask("And that bank?", history=[{"q": "Which bank is worst?", "a": "BNK01."}])
    sent = client.sent[0][1]
    assert [c.role for c in sent] == ["user", "model", "user"] and sent[0].parts[0].text == "Which bank is worst?"


def test_each_query_is_reported_as_it_runs(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = FakeClient([reply(call("run_sql", {"sql": "SELECT 1"})), reply(types.Part(text="There are 44807."))])
    monkeypatch.setattr(agent_mod, "_gemini_client", lambda: client)
    steps = []
    out = agent_mod.Agent(FakeReader(), lambda *x: {}, ACTION_TYPES).ask("How many?", on_step=steps.append)
    assert steps == [{"kind": "sql", "sql": "SELECT 1", "ms": 1, "rows": 1}] and out["grounded"]


def test_a_failed_query_goes_back_to_the_model_and_is_shown(monkeypatch):
    class Bad(FakeReader):
        def query(self, sql):
            raise RuntimeError("object X not found")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = FakeClient([reply(call("run_sql", {"sql": "SELECT X"})), reply(types.Part(text="I don't have that data."))])
    monkeypatch.setattr(agent_mod, "_gemini_client", lambda: client)
    steps = []
    a = agent_mod.Agent(Bad(), lambda *x: {}, ACTION_TYPES)
    out = a.ask("x", on_step=steps.append)
    assert steps[0]["error"] == "object X not found" and out["answer"] == "I don't have that data."


def test_when_the_model_fails_the_answer_says_it_did_not_come_from_the_model(monkeypatch):
    class Down:
        models = None

    def fail():
        raise ConnectionError("quota")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(agent_mod, "_gemini_client", fail)
    a = agent_mod.Agent(FakeReader(), lambda *x: {}, ACTION_TYPES)
    out = a.ask("What is the weather?")
    assert "not the model" in out["fallback"] and out["queries"] == []


def test_the_prompt_carries_the_real_columns_and_keeps_the_rules():
    text = agent_mod.system_prompt("RECON.EXCEPTIONS: EXC_ID, CLASS")
    assert "RECON.EXCEPTIONS: EXC_ID, CLASS" in text and "SYNTHETIC" in text and "untrusted" in text


def _down(code):
    e = RuntimeError("busy")
    e.code = code
    return e


def test_a_busy_model_hands_the_whole_question_to_the_next_one(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(agent_mod, "MODELS", ["first", "second"])
    tried = []

    def turn(self, question, history, on_step, model):
        tried.append(model)
        if model == "first":
            raise _down(503)
        return {"mode": "gemini", "answer": "ok", "queries": [], "grounded": True, "ungrounded": [], "proposal": None}
    monkeypatch.setattr(agent_mod.Agent, "_gemini", turn)
    a = agent_mod.Agent(FakeReader(), lambda *x: {}, ACTION_TYPES)
    a.good_model = "first"
    steps = []
    out = a.ask("x", on_step=steps.append)
    assert tried == ["first", "second"] and out["model"] == "second" and a.good_model == "second"
    assert steps == [{"kind": "note", "text": "first is busy, trying another model"}]
    tried.clear()
    a.ask("again")
    assert tried == ["second"]        # the next question goes straight to the model that worked


def test_a_refused_request_does_not_wander_through_every_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(agent_mod, "MODELS", ["first", "second"])
    tried = []

    def turn(self, question, history, on_step, model):
        tried.append(model)
        raise _down(400)
    monkeypatch.setattr(agent_mod.Agent, "_gemini", turn)
    out = agent_mod.Agent(FakeReader(), lambda *x: {}, ACTION_TYPES).ask("x")
    assert len(tried) == 1 and "not the model" in out["fallback"]


@pytest.mark.parametrize("code,expected", [(429, True), (503, True), (500, True), (400, False), (403, False), (None, False)])
def test_only_passing_failures_are_retried(code, expected):
    assert agent_mod.retryable(_down(code)) is expected


def test_timeouts_are_retried():
    assert agent_mod.retryable(TimeoutError()) and agent_mod.retryable(type("ReadTimeout", (Exception,), {})())


def test_a_paise_figure_may_be_quoted_in_rupees():
    a = agent_mod.Agent(FakeReader(), lambda *x: {}, ACTION_TYPES)
    results = [{"columns": ["N", "ADDED_PAISE"], "rows": [[5, 320000]]}]
    assert a._guarded("It adds ₹3,200 tomorrow across 5 cases.", results)["grounded"]


def test_only_a_paise_column_gets_that_conversion():
    a = agent_mod.Agent(FakeReader(), lambda *x: {}, ACTION_TYPES)
    assert not a._guarded("About 3,200 of them.", [{"columns": ["N"], "rows": [[320000]]}])["grounded"]


def test_a_number_worked_out_in_the_models_head_is_still_refused():
    a = agent_mod.Agent(FakeReader(), lambda *x: {}, ACTION_TYPES)
    assert not a._guarded("That is ₹640 a case.", [{"columns": ["N", "ADDED_PAISE"], "rows": [[5, 320000]]}])["grounded"]
