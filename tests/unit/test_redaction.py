"""Redaction: sensitive values never reach the logs."""
import json

from observability.logger import log_replay
from replay.outcomes import ReplayResult, ReplayStatus
from safety.redaction import redact_any

from agent.loop import AgentRunResult, TranscriptStep
from observability.logger import log_discovery


def test_password_fields_are_hidden_at_any_depth():
    data = {"inputs": {"username": "john", "password": "demo"}}
    assert redact_any(data) == {"inputs": {"username": "john", "password": "[REDACTED]"}}


def test_text_typed_into_a_password_field_is_hidden():
    step = {"element_name": "Password", "text": "demo"}
    assert redact_any(step)["text"] == "[REDACTED]"


def test_text_typed_into_other_fields_is_kept():
    step = {"element_name": "Username", "text": "john"}
    assert redact_any(step)["text"] == "john"


def test_known_secret_values_are_hidden_inside_free_text():
    goal = "Log in with username 'john' and password 'demo'."
    assert redact_any(goal, sensitive_values={"demo"}) == "Log in with username 'john' and password '[REDACTED]'."


def test_ssn_and_card_numbers_are_hidden():
    text = redact_any("SSN 123-45-6789, card 4111111111111111")
    assert "123-45-6789" not in text and "4111111111111111" not in text


def test_account_fields_keep_only_the_last_two_digits():
    assert redact_any({"from_account_id": "13344"}) == {"from_account_id": "***44"}


def test_known_account_numbers_are_masked_inside_free_text():
    text = "Select '13344' in 'From account #:'"
    assert redact_any(text, masked_values={"13344"}) == "Select '***44' in 'From account #:'"


def test_account_number_inside_a_longer_number_is_left_alone():
    assert redact_any("ref 133445", masked_values={"13344"}) == "ref 133445"


def test_replay_log_hides_secrets_and_masks_accounts_in_every_field(tmp_path):
    result = ReplayResult(
        status=ReplayStatus.FAILURE, 
        capability_id="parabank.request_loan", 
        failed_step=3,
        expected="Select '13344' in 'From account #:'",
        observed="password 'wrong' was echoed back",
        error="Step 3 failed for account 13344 with password 'wrong'",
    )
    inputs = {"username": "john", "password": "wrong", "from_account_id": "13344"}
    path = log_replay(result, str(tmp_path), inputs=inputs, run_id="test")
    text = path.read_text()
    assert "wrong" not in text
    assert "13344" not in text
    assert "***44" in text


def test_discovery_log_masks_the_runs_own_accounts_only(tmp_path):
    step = TranscriptStep(
        step_num=3, page_url="http://localhost:8080/parabank/requestloan.htm",
        tool_name="select_option",
        tool_input={"element_name": "From account #:", "option_value": "12456"},
        success=True,
        detail="Options: 12345, 12456. Your new account number: 13899",
    )
    result = AgentRunResult(
        goal="Request a loan", 
        success=True, 
        stop_reason="goal_met",
        transcript=[step], 
        outputs={"new_account_id": "13899"}
    )
    path = log_discovery(result, str(tmp_path), run_id="test")
    text = path.read_text()
    assert "12456" not in text and "***56" in text      
    assert "13899" not in text and "***99" in text    
    assert "12345" in text                  