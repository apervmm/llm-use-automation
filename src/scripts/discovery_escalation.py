"""
Manual verification for Module 3: discovery-side stuck detection & escalation.

Run: PYTHONPATH=src python scripts/verify_module3.py

The agent is deliberately given too few steps to finish a 3-step login.
When the prompt appears, press Enter to resume (grants a bounded step
extension) or type 'abort' to stop the run outright — try both across two
runs to exercise both branches.
"""
from dotenv import load_dotenv
load_dotenv()

import os
from surface.browser import BrowserSession
from agent.llm_client import LLMClient
from agent.loop import AgentLoop
from escalation.operator_cli import to_operator

USERNAME = os.environ.get("PARABANK_USERNAME_SUCCESS", "john")
PASSWORD = os.environ.get("PARABANK_PASSWORD_SUCCESS", "demo")

with BrowserSession(headless=False) as session:
    llm = LLMClient()
    agent = AgentLoop(
        session, llm,
        max_steps=2,  # deliberately too few for a 3-step login flow
        evidence_dir="evidence/verify_module3",
        on_escalation=to_operator,
    )
    result = agent.run(
        goal=(
            f"Log in with username '{USERNAME}' and password '{PASSWORD}'. "
            "When calling done, include 'login_succeeded' and 'message'."
        ),
        start_url="https://parabank.parasoft.com/parabank/index.htm",
    )

print(f"\nResult: success={result.success}, stop_reason={result.stop_reason}, escalations={result.escalations}")