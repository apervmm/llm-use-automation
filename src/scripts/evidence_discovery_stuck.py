"""
Evidence generation for DISCOVERY_STUCK escalation (both operator decisions).
max_steps is intentionally set below what a 3-step login needs — this is a
genuine trigger of the real stuck-detection logic, not a simulated one.
"""
from dotenv import load_dotenv
load_dotenv()

from datetime import datetime, timezone
import os

from surface.browser import BrowserSession
from agent.llm_client import LLMClient
from agent.loop import AgentLoop
from escalation.operator_cli import to_operator
from observability.logger import log_discovery

USERNAME = os.environ.get("PARABANK_USERNAME_SUCCESS", "john")
PASSWORD = os.environ.get("PARABANK_PASSWORD_SUCCESS", "demo")

ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

GOAL = (
    f"Log in with username '{USERNAME}' and password '{PASSWORD}'. "
    "When calling done, include output keys 'login_succeeded' and 'message'."
)

print("=" * 70)
print("RUN 1 of 2 — max_steps exhausted, operator RESUMES (press Enter)")
print("=" * 70)
resumed_dir = f"evidence/discovery_stuck_resumed_{ts}"
with BrowserSession(headless=False) as session:
    agent = AgentLoop(
        session, LLMClient(), max_steps=2, evidence_dir=resumed_dir,
        on_escalation=to_operator,
    )
    result_resumed = agent.run(goal=GOAL, start_url="https://parabank.parasoft.com/parabank/index.htm")
log_discovery(result_resumed, resumed_dir, sensitive_values=[PASSWORD])
print(f"\nSaved to {resumed_dir} — success={result_resumed.success}, stop_reason={result_resumed.stop_reason}")

print()
print("=" * 70)
print("RUN 2 of 2 — max_steps exhausted, operator ABORTS (type 'abort')")
print("=" * 70)
aborted_dir = f"evidence/discovery_stuck_aborted_{ts}"
with BrowserSession(headless=False) as session:
    agent = AgentLoop(
        session, LLMClient(), max_steps=2, evidence_dir=aborted_dir,
        on_escalation=to_operator,
    )
    result_aborted = agent.run(goal=GOAL, start_url="https://parabank.parasoft.com/parabank/index.htm")
log_discovery(result_aborted, aborted_dir, sensitive_values=[PASSWORD])
print(f"\nSaved to {aborted_dir} — success={result_aborted.success}, stop_reason={result_aborted.stop_reason}")