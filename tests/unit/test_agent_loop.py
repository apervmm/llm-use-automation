from types import SimpleNamespace

from agent.loop import AgentLoop
from escalation.handoff import OperatorDecision


LOGIN = "http://localhost:8080/parabank/index.htm"


def tool(name: str, **tool_input):
    """One tool_use block, shaped like the Anthropic SDK's."""
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=f"toolu_{name}")


class ScriptedLLM:
    """Stands in for LLMClient: returns one scripted response per decide() call. None = no tool call."""

    def __init__(self, *blocks):
        self.responses = [SimpleNamespace(content=[b] if b else []) for b in blocks]
        self.calls = 0

    def decide(self, messages, system_prompt, tools):
        response = self.responses[self.calls]
        self.calls += 1
        return response


def operator(decision: OperatorDecision):
    """Stands in for to_operator: always gives the same answer."""
    def on_escalation(request, state):
        if decision == OperatorDecision.RESUME:
            state.resume_automation()
        return decision, {"reason": request.reason.value, "operator_decision": decision.value}
    return on_escalation


MISSING = tool("click", element_name="No Such Button")


def test_scripted_login_reaches_the_goal(session, tmp_path):
    llm = ScriptedLLM(
        tool("type_text", element_name="Username", text="john"),
        tool("type_text", element_name="Password", text="demo"),
        tool("click", element_name="Log In"),
        tool("done", outputs={"login_succeeded": "true"}),
    )
    result = AgentLoop(session, llm, evidence_dir=str(tmp_path)).run("Log in", LOGIN)

    assert result.success and result.stop_reason == "goal_met"
    assert [t.tool_name for t in result.transcript] == ["type_text", "type_text", "click", "done"]
    assert all(t.success for t in result.transcript)
    assert result.transcript[0].resolved_ref is not None
    assert result.outputs == {"login_succeeded": "true"}


def test_three_failed_actions_escalate_and_the_operator_aborts(session, tmp_path):
    llm = ScriptedLLM(MISSING, MISSING, MISSING)
    loop = AgentLoop(session, llm, evidence_dir=str(tmp_path), on_escalation=operator(OperatorDecision.ABORT))
    result = loop.run("Click a button that isn't there", LOGIN)

    assert result.stop_reason == "aborted_by_operator"
    assert [e["reason"] for e in result.escalations] == ["discovery_stuck"]
    assert [t.success for t in result.transcript] == [False, False, False]


def test_resume_after_being_stuck_lets_the_agent_finish(session, tmp_path):
    llm = ScriptedLLM(MISSING, MISSING, MISSING, tool("done", outputs={}))
    loop = AgentLoop(session, llm, evidence_dir=str(tmp_path), on_escalation=operator(OperatorDecision.RESUME))
    result = loop.run("Recover after help", LOGIN)

    assert result.success and result.stop_reason == "goal_met"
    assert len(result.escalations) == 1
    assert llm.calls == 4


def test_step_limit_without_an_operator_stops_the_run(session, tmp_path):
    llm = ScriptedLLM(MISSING)
    result = AgentLoop(session, llm, max_steps=1, evidence_dir=str(tmp_path)).run("Too long", LOGIN)

    assert result.stop_reason == "max_steps_exceeded"
    assert llm.calls == 1


def test_no_tool_call_without_an_operator_stops_the_run(session, tmp_path):
    result = AgentLoop(session, ScriptedLLM(None), evidence_dir=str(tmp_path)).run("Say nothing", LOGIN)
    assert result.stop_reason == "no_tool_call"


def test_entry_page_outside_the_allowlist_stops_before_the_model_is_asked(session, tmp_path):
    llm = ScriptedLLM()
    result = AgentLoop(session, llm, evidence_dir=str(tmp_path)).run("Anything", "https://example.com")

    assert result.stop_reason.startswith("entry_unreachable")
    assert llm.calls == 0