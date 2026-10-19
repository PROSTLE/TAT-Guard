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
