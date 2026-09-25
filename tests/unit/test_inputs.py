"""Input validation: bad inputs are rejected before replay touches the browser."""
from artifact.schema import Step, StepAction
from replay.executor import input_errors, replay
from replay.outcomes import ReplayStatus


def test_valid_inputs_have_no_errors(loan_capability, valid_loan_inputs):
    assert input_errors(loan_capability, valid_loan_inputs) == []


def test_misspelled_input_name_is_reported_as_missing_and_unknown(loan_capability):
    errors = input_errors(loan_capability, {"amout": "1000", "down_payment": "10", "from_account_id": "13344"})
    assert "missing required input(s): ['amount']" in errors
    assert "unknown input(s): ['amout']" in errors


def test_every_missing_input_is_listed(loan_capability):
    errors = input_errors(loan_capability, {"amount": "1000"})
    assert "missing required input(s): ['down_payment', 'from_account_id']" in errors


def test_text_for_a_number_input_is_rejected(loan_capability, valid_loan_inputs):
    errors = input_errors(loan_capability, {**valid_loan_inputs, "amount": "abc"})
    assert "'amount' must be a number, got 'abc'" in errors


def test_decimal_numbers_are_accepted(loan_capability, valid_loan_inputs):
    assert input_errors(loan_capability, {**valid_loan_inputs, "amount": "1000.50"}) == []


def test_placeholder_without_a_declared_input_is_reported(loan_capability, valid_loan_inputs):
    loan_capability.steps.append(Step(step_num=6, action=StepAction.TYPE_TEXT, value="{memo}"))
    errors = input_errors(loan_capability, valid_loan_inputs)
    assert "steps reference params with no value: ['memo']" in errors


def test_replay_rejects_bad_inputs_before_touching_the_browser(loan_capability, valid_loan_inputs):
    # session=None: crashes on browser runs
    result = replay(None, loan_capability, {**valid_loan_inputs, "amount": "abc"})
    assert result.status == ReplayStatus.FAILURE
    assert result.failed_step == 0
    assert "'amount' must be a number" in result.error
    assert result.escalations == []