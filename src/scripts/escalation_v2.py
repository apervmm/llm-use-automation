"""
Manual verification for Module 2: an operator's RESUME decision must actually
resume the run, not just delay an inevitable FAILURE.

Run: python scripts/verify_module2.py
You'll be prompted twice — read the instructions printed before each prompt.
"""
from dotenv import load_dotenv
load_dotenv()

import os
from surface.browser import BrowserSession
from artifact import store
from artifact.schema import RiskLevel
from replay.executor import replay
from replay.outcomes import ReplayStatus
from escalation.operator_cli import to_operator

USERNAME = os.environ.get("PARABANK_USERNAME_SUCCESS", "john")
PASSWORD = os.environ.get("PARABANK_PASSWORD_SUCCESS", "demo")
GOOD_URL = "https://parabank.parasoft.com/parabank/index.htm"
BAD_URL = "https://parabank.parasoft.com/parabank/nonexistent.htm"

capability = store.load("parabank.login")

print("=" * 70)
print("SCENARIO A — step failure, operator fixes the live session, RESUME")
print("=" * 70)
print(
    "The browser will open on a broken page (step 1 will fail to find the "
    "username field). When the prompt appears, switch to the open browser "
    f"window, manually navigate it to:\n  {GOOD_URL}\n"
    "then come back here and press Enter to resume.\n"
)

with BrowserSession(headless=False) as session:
    broken = capability.model_copy(deep=True)
    broken.entry_url = BAD_URL
    result_a = replay(
        session, broken, {"username": USERNAME, "password": PASSWORD},
        on_escalation=to_operator,
    )

print(f"\nScenario A result: {result_a.status.value}")
print("PASS — retried after intervention and completed." if result_a.status == ReplayStatus.SUCCESS
      else f"Did not reach SUCCESS. Detail: {result_a.error}")

print()
print("=" * 70)
print("SCENARIO B — risky capability, operator approves, RESUME")
print("=" * 70)
print("This run is marked RISKY. Press Enter at the prompt to approve it "
      "(no manual browser action needed).\n")

with BrowserSession(headless=False) as session:
    risky = capability.model_copy(deep=True)
    risky.risk_level = RiskLevel.RISKY
    result_b = replay(
        session, risky, {"username": USERNAME, "password": PASSWORD},
        confirmed=False,
        on_escalation=to_operator,
    )

print(f"\nScenario B result: {result_b.status.value}")
print("PASS — operator approval was honored." if result_b.status == ReplayStatus.SUCCESS
      else f"Did not reach SUCCESS. Detail: {result_b.error}")