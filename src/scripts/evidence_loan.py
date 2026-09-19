"""
Discovery + record + replay evidence for parabank.request_loan.

Uses ParaBank's well-known public demo login (john/demo), which persists
across sessions unlike freshly self-registered accounts. Note: because this
is a shared public demo account, its exact set of accounts/balances can
shift between runs if other testers are using it concurrently — the agent
selects a from-account dynamically for this reason rather than assuming a
fixed account number.
"""
from dotenv import load_dotenv
load_dotenv()

import os
from datetime import datetime, timezone

from surface.browser import BrowserSession
from agent.llm_client import LLMClient
from agent.loop import AgentLoop, TranscriptStep
from artifact.recorder import record
from artifact.schema import Checkpoint, OutcomeRule
from artifact import store
from replay.executor import replay
from escalation.operator_cli import to_operator
from observability.logger import log_discovery, log_replay
from replay.outcomes import ReplayStatus

USERNAME = os.environ.get("PARABANK_USERNAME_LOAN", "john")
PASSWORD = os.environ.get("PARABANK_PASSWORD_LOAN", "demo")

LOAN_AMOUNT = os.environ.get("LOAN_AMOUNT", "1000")
LOAN_DOWN_PAYMENT = os.environ.get("LOAN_DOWN_PAYMENT", "10")

ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def find_chosen_account(transcript: list[TranscriptStep]) -> str:
    for t in transcript:
        if t.tool_name == "select_option" and t.success:
            return t.tool_input["option_value"]
    raise AssertionError(
        "Agent never called select_option — cannot determine which account to parameterize."
    )





# DISCOVERY: log in, then apply for a loan, on one shared session
print(f"\n\n=== DISCOVERY: login then apply for a loan of ")
login_discovery_dir = f"evidence/discovery_login_for_loan_{ts}"
loan_discovery_dir = f"evidence/discovery_request_loan_{ts}"

with BrowserSession(headless=False) as session:
    llm = LLMClient()

    login_agent = AgentLoop(session, llm, max_steps=8, evidence_dir=login_discovery_dir)
    login_result = login_agent.run(
        goal=(
            f"Log in with username '{USERNAME}' and password '{PASSWORD}'. "
            "When calling done, include output keys 'login_succeeded' and 'message'."
        ),
        start_url="https://parabank.parasoft.com/parabank/index.htm",
    )
    log_discovery(login_result, login_discovery_dir, sensitive_values=[PASSWORD])
    assert login_result.success, f"Login discovery failed: {login_result.stop_reason}"
    assert login_result.outputs.get("login_succeeded") == "true", (
        f"Login discovery ran to completion but did NOT authenticate — "
        f"outputs: {login_result.outputs}. Refusing to proceed to loan "
        f"discovery with an unauthenticated session."
    )
    print(f"Login discovery saved to {login_discovery_dir}\n")

    login_capability = record(
        run_result=login_result,
        capability_id="parabank.login",
        entry_url="https://parabank.parasoft.com/parabank/index.htm",
        param_map={USERNAME: "username", PASSWORD: "password"},
        output_keys=["login_succeeded", "message"],
        checkpoint=Checkpoint(kind="url_contains", expected="/overview.htm"),
        description="Log into ParaBank with a username and password.",
    )
    login_capability.outcome_rules.append(
        OutcomeRule(
            name="invalid_credentials", kind="text_visible",
            expected="could not be verified",
            description="Wrong username/password",
        )
    )
    store.save(login_capability)
    print(f"parabank.login recorded fresh (version={login_capability.version})\n")

    loan_agent = AgentLoop(session, llm, max_steps=10, evidence_dir=loan_discovery_dir)
    loan_result = loan_agent.run(
        goal=(
            f"Apply for a loan with amount '{LOAN_AMOUNT}' and down payment "
            f"'{LOAN_DOWN_PAYMENT}'. For 'From account #', look at the "
            "dropdown's available options and select one using "
            "select_option — do this explicitly even if there is only one "
            "option available, so the choice is recorded. Then click Apply "
            "Now and wait for the 'Loan Request Processed' result to appear "
            "(it may take a moment to render — re-check the page if you "
            "don't see it immediately). When calling done, include output "
            "keys 'loan_status' (the exact text next to Status:) and, if "
            "approved, 'new_account_id' (read it from the 'Your new "
            "account number' link)."
        ),
        start_url="https://parabank.parasoft.com/parabank/requestloan.htm",
    )
    log_discovery(loan_result, loan_discovery_dir)
    print(f"Loan discovery saved to {loan_discovery_dir} — success={loan_result.success}\n")

assert loan_result.success, f"Loan discovery failed: {loan_result.stop_reason}"
chosen_account = find_chosen_account(loan_result.transcript)
print(f"Agent selected account: {chosen_account}")





# RECORD: turn the loan discovery run into a reusable capability
print("\n\n=== RECORD: turn the loan discovery run into a reusable capability ===")
loan_capability = record(
    run_result=loan_result,
    capability_id="parabank.request_loan",
    entry_url="https://parabank.parasoft.com/parabank/requestloan.htm",
    param_map={
        LOAN_AMOUNT: "amount",
        LOAN_DOWN_PAYMENT: "down_payment",
        chosen_account: "from_account_id",
    },
    output_keys=["loan_status", "new_account_id"],
    checkpoint=Checkpoint(kind="text_visible", expected="Congratulations, your loan has been approved."),
    description="Apply for a loan against an existing ParaBank account.",
)
loan_capability.outcome_rules.extend([
    OutcomeRule(name="loan_approved", kind="text_visible",
                expected="Congratulations, your loan has been approved.",
                description="Loan approved"),
    OutcomeRule(name="insufficient_funds_for_down_payment", kind="text_visible",
                expected="You do not have sufficient funds for the given down payment.",
                description="Denied: insufficient funds for the given down payment"),
    OutcomeRule(name="insufficient_funds_and_down_payment", kind="text_visible",
                expected="We cannot grant a loan in that amount with your available funds and down payment.",
                description="Denied: insufficient funds and down payment"),
    OutcomeRule(name="insufficient_funds", kind="text_visible",
                expected="We cannot grant a loan in that amount with your available funds.",
                description="Denied: insufficient funds"),
    OutcomeRule(name="insufficient_down_payment", kind="text_visible",
                expected="We cannot grant a loan in that amount with the given down payment.",
                description="Denied: insufficient down payment"),
])
artifact_path = store.save(loan_capability)
print(f"Artifact saved to {artifact_path} (risk_level={loan_capability.risk_level.value})")




# REPLAY: chain login + request_loan on a FRESH session, deterministically
print("\n\n=== REPLAY: chain login + request_loan on a FRESH session, deterministically ===")
login_capability = store.load("parabank.login")
replay_dir = f"evidence/replay_request_loan_{ts}"

with BrowserSession(headless=False) as session:
    login_replay_result = replay(session, login_capability, {"username": USERNAME, "password": PASSWORD})
    assert login_replay_result.status == ReplayStatus.SUCCESS, (
        f"Login replay failed — status={login_replay_result.status.value}, "
        f"error={login_replay_result.error}"
    )

    loan_inputs = {
        "amount": LOAN_AMOUNT,
        "down_payment": LOAN_DOWN_PAYMENT,
        "from_account_id": chosen_account,
    }
    loan_replay_result = replay(
        session, loan_capability, loan_inputs,
        confirmed=False,
        on_escalation=to_operator,
    )

log_replay(loan_replay_result, replay_dir, loan_inputs)
print(f"Replay saved to {replay_dir} — status={loan_replay_result.status.value}")
print(f"outcome={loan_replay_result.outcome_name}" if loan_replay_result.outcome_name else "")