"""Recording: a successful agent run becomes a safe, parameterized artifact."""
import pytest

from agent.loop import AgentRunResult, TranscriptStep
from artifact.recorder import record
from artifact.schema import Checkpoint, ParamType, RiskLevel, StepAction

LOGIN_URL = "http://localhost:8080/parabank/index.htm"
LOAN_URL = "http://localhost:8080/parabank/requestloan.htm"


def _step(n: int, tool: str, tool_input: dict, success: bool = True) -> TranscriptStep:
    return TranscriptStep(step_num=n, page_url=LOGIN_URL, tool_name=tool,
                          tool_input=tool_input, success=success, detail="")


def _login_run(transcript=None, success=True) -> AgentRunResult:
    transcript = transcript or [
        _step(1, "type_text", {"element_name": "Username", "text": "john"}),
        _step(2, "type_text", {"element_name": "Password", "text": "demo"}),
        _step(3, "click", {"element_name": "Log In"}),
        _step(4, "done", {"outputs": {"login_succeeded": "true"}}),
    ]
    return AgentRunResult(
        goal="Log in with username 'john' and password 'demo'.",
        success=success, stop_reason="goal_met",
        transcript=transcript, outputs={"login_succeeded": "true"},
    )


def _record_login(run, param_map=None):
    return record(
        run_result=run,
        capability_id="login",
        entry_url=LOGIN_URL,
        param_map=param_map or {"john": "username", "demo": "password"},
        output_keys=["login_succeeded"],
        checkpoint=Checkpoint(kind="url_contains", expected="overview.htm"),
        description=f"Recorded from goal: {run.goal}",
    )


def test_typed_values_are_saved_as_placeholders():
    capability = _record_login(_login_run())
    typed = [s.value for s in capability.steps if s.action == StepAction.TYPE_TEXT]
    assert typed == ["{username}", "{password}"]


def test_password_appears_nowhere_in_the_artifact():
    capability = _record_login(_login_run())
    assert "demo" not in capability.model_dump_json()
    assert "{password}" in capability.description
    assert next(p for p in capability.inputs if p.name == "password").example == "[REDACTED]"


def test_recording_fails_if_a_parameter_never_matched_a_typed_value():
    # Simulates an unexpanded env var: the literal never appears in the transcript.
    with pytest.raises(ValueError, match="never matched"):
        _record_login(_login_run(), param_map={"john": "username", "${PARABANK_PASSWORD}": "password"})


def test_failed_actions_are_left_out_and_steps_stay_numbered():
    run = _login_run(transcript=[
        _step(1, "type_text", {"element_name": "Username", "text": "john"}),
        _step(2, "click", {"element_name": "Nope"}, success=False),
        _step(3, "type_text", {"element_name": "Password", "text": "demo"}),
        _step(4, "click", {"element_name": "Log In"}),
    ])
    capability = _record_login(run)
    assert [s.step_num for s in capability.steps] == [1, 2, 3]
    assert all("Nope" not in s.description for s in capability.steps)


def test_login_is_saved_with_a_qualified_id_and_as_safe():
    capability = _record_login(_login_run())
    assert capability.capability_id == "parabank.login"
    assert capability.risk_level == RiskLevel.SAFE


def test_cannot_record_from_a_failed_run():
    with pytest.raises(ValueError):
        _record_login(_login_run(success=False))


def test_loan_is_recorded_as_risky_with_number_inputs():
    run = AgentRunResult(
        goal="Apply for a loan with amount '1000' and down payment '10'.",
        success=True, stop_reason="goal_met",
        transcript=[
            _step(1, "type_text", {"element_name": "Loan Amount: $", "text": "1000"}),
            _step(2, "type_text", {"element_name": "Down Payment: $", "text": "10"}),
            _step(3, "select_option", {"element_name": "From account #:", "option_value": "13344"}),
            _step(4, "click", {"element_name": "Apply Now"}),
        ],
        outputs={"loan_status": "Approved", "new_account_id": "14000"},
    )
    capability = record(
        run_result=run,
        capability_id="request_loan",
        entry_url=LOAN_URL,
        param_map={"1000": "amount", "10": "down_payment", "13344": "from_account_id"},
        output_keys=["loan_status", "new_account_id"],
        checkpoint=Checkpoint(kind="text_visible", expected="Congratulations"),
        description=f"Recorded from goal: {run.goal}",
        outcome_derived_outputs=["loan_status"],
    )
    assert capability.capability_id == "parabank.request_loan"
    assert capability.risk_level == RiskLevel.RISKY
    assert {p.name: p.type for p in capability.inputs} == {
        "amount": ParamType.NUMBER, "down_payment": ParamType.NUMBER, "from_account_id": ParamType.NUMBER,
    }
    assert capability.steps[2].description == "Select '{from_account_id}' in 'From account #:'"
    assert "'{amount}'" in capability.description and "'{down_payment}'" in capability.description