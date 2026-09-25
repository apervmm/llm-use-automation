"""Redaction: sensitive values never reach the logs."""
import json

from observability.logger import log_replay
from replay.outcomes import ReplayResult, ReplayStatus
from safety.redaction import redact_any


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


def test_short_account_numbers_are_not_hidden_known_limit():
    assert redact_any("account 13344") == "account 13344"


def test_replay_log_hides_the_password_input(tmp_path):
    result = ReplayResult(
        status=ReplayStatus.BUSINESS_OUTCOME, 
        capability_id="parabank.login",
        outcome_name="invalid_credentials"
    )
    path = log_replay(result, str(tmp_path), inputs={"username": "john", "password": "wrong"}, run_id="test")
    assert json.loads(path.read_text())["inputs"]["password"] == "[REDACTED]"
    assert "wrong" not in path.read_text()