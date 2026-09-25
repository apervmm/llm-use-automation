"""replay outs"""
from artifact.schema import Capability, OutcomeRule, OutputField
from replay.executor import _check_outcomes, _extract_outputs, _fill
from replay.outcomes import ReplayStatus


class FakePage:
    """Fake BrowserSession where only the page text and URL are read."""
    def __init__(self, text: str = "", url: str = "http://localhost:8080/parabank/requestloan.htm"):
        self.text, self.url = text, url

    def wait(self, ms: int) -> None:
        pass

    def get_visible_text(self) -> str:
        return self.text

    def get_url(self) -> str:
        return self.url


SPECIFIC = OutcomeRule(
    name="insufficient_funds_and_down_payment", 
    kind="text_visible",
    expected="available funds and down payment"
)
GENERAL = OutcomeRule(
    name="insufficient_funds", 
    kind="text_visible",
    expected="available funds"
)


def test_first_matching_outcome_rule_wins():
    page = FakePage("We cannot grant a loan in that amount with your available funds and down payment.")
    assert _check_outcomes(page, [SPECIFIC, GENERAL]) == "insufficient_funds_and_down_payment"


def test_no_matching_rule_returns_none():
    assert _check_outcomes(FakePage("Something unexpected happened."), [SPECIFIC, GENERAL]) is None


def test_url_rules_match_the_current_address():
    rule = OutcomeRule(name="logged_out", kind="url_contains", expected="index.htm")
    assert _check_outcomes(FakePage(url="http://localhost:8080/parabank/index.htm"), [rule]) == "logged_out"


def test_derived_output_reports_success(loan_capability):
    outputs = _extract_outputs(loan_capability, {"new_account_id": "14000"}, status=ReplayStatus.SUCCESS)
    assert outputs == {"loan_status": "success", "new_account_id": "14000"}


def test_derived_output_reports_the_business_outcome_name(loan_capability):
    outputs = _extract_outputs(loan_capability, {}, status=ReplayStatus.BUSINESS_OUTCOME,
                               outcome_name="insufficient_funds")
    assert outputs["loan_status"] == "insufficient_funds"
    assert outputs["new_account_id"] is None


def test_success_flag_output_follows_the_result():
    capability = Capability(
        capability_id="parabank.login", 
        entry_url="http://localhost:8080/parabank/index.htm",
        outputs=[OutputField(name="login_succeeded")]
    )
    assert _extract_outputs(
        capability, 
        {}, 
        status=ReplayStatus.SUCCESS
    ) == {"login_succeeded": "true"}

    assert _extract_outputs(
        capability, 
        {}, 
        status=ReplayStatus.BUSINESS_OUTCOME,
        outcome_name="invalid_credentials"
    ) == {"login_succeeded": "false"}


def test_failure_report_shows_the_callers_actual_value():
    assert _fill(
        "Select '{from_account_id}' in 'From account #:'", 
        {"from_account_id": "99999"}
    ) == "Select '99999' in 'From account #:'"