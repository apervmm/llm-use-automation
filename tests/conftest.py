"""Shared fixtures for all tests."""
import urllib.request

import pytest

from artifact import store
from artifact.schema import (
    Capability, Checkpoint, InputParam, OutcomeRule, OutputField,
    ParamType, RiskLevel, Step, StepAction,
)

LOAN_URL = "http://localhost:8080/parabank/requestloan.htm"
PARABANK = "http://localhost:8080/parabank/index.htm"


def parabank_running() -> bool:
    try:
        urllib.request.urlopen(PARABANK, timeout=2)
        return True
    except Exception:
        return False


@pytest.fixture
def session():
    """A hidden browser for browser tests; skipped if ParaBank isn't running."""
    if not parabank_running():
        pytest.skip("ParaBank not running (docker compose up -d)")
    from surface.browser import BrowserSession   
    s = BrowserSession(headless=True)
    yield s
    s.close()


@pytest.fixture
def artifact_dir(tmp_path, monkeypatch):
    """Point the artifact store at a temp folder, so tests never touch artifacts/."""
    folder = tmp_path / "artifacts"
    monkeypatch.setattr(store, "ARTIFACT_DIR", folder)
    return folder


@pytest.fixture
def loan_capability() -> Capability:
    """A minimal loan capability built in code, so tests don't depend on recorded artifacts."""
    return Capability(
        capability_id="parabank.request_loan",
        entry_url=LOAN_URL,
        inputs=[
            InputParam(name="amount", type=ParamType.NUMBER),
            InputParam(name="down_payment", type=ParamType.NUMBER),
            InputParam(name="from_account_id", type=ParamType.NUMBER),
        ],
        outputs=[
            OutputField(name="loan_status", derived_from_outcome=True),
            OutputField(name="new_account_id", source_label="new_account_id"),
        ],
        steps=[
            Step(step_num=1, action=StepAction.TYPE_TEXT, value="{amount}"),
            Step(step_num=2, action=StepAction.TYPE_TEXT, value="{down_payment}"),
            Step(step_num=3, action=StepAction.SELECT_OPTION, value="{from_account_id}",
                 description="Select '{from_account_id}' in 'From account #:'"),
            Step(step_num=4, action=StepAction.CLICK, description="Click 'Apply Now'"),
            Step(step_num=5, action=StepAction.READ, read_label="new_account_id"),
        ],
        checkpoint=Checkpoint(kind="text_visible", expected="Congratulations, your loan has been approved."),
        outcome_rules=[
            OutcomeRule(name="insufficient_funds", kind="text_visible",
                        expected="You do not have sufficient funds"),
        ],
        risk_level=RiskLevel.RISKY,
    )


@pytest.fixture
def valid_loan_inputs() -> dict:
    return {"amount": "1000", "down_payment": "10", "from_account_id": "13344"}