"""
Evidence generation for RISKY_CONFIRMATION escalation (both operator decisions).

NOTE ON SCOPE: this uses parabank.login with risk_level manually forced to
RISKY as a stand-in for a genuinely risky capability (e.g. transfer_funds).
The mechanism exercised here is real and identical to what a real money-
moving capability would trigger; only the underlying action is a stand-in.
See NOTE.md written into each evidence directory, and REPORT.md Cuts.
"""
from dotenv import load_dotenv
load_dotenv()

from datetime import datetime, timezone
from pathlib import Path
import os

from surface.browser import BrowserSession
from artifact import store
from artifact.schema import RiskLevel
from replay.executor import replay
from escalation.operator_cli import to_operator
from observability.logger import log_replay

USERNAME = os.environ.get("PARABANK_USERNAME_SUCCESS", "john")
PASSWORD = os.environ.get("PARABANK_PASSWORD_SUCCESS", "demo")

ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
inputs = {"username": USERNAME, "password": PASSWORD}


def write_note(evidence_dir: str, decision: str):
    Path(evidence_dir).mkdir(parents=True, exist_ok=True)
    Path(evidence_dir, "NOTE.md").write_text(
        "# Scope note\n\n"
        "This evidence demonstrates the RISKY_CONFIRMATION escalation path "
        "using `parabank.login` with `risk_level` manually forced to `RISKY`, "
        "as a stand-in for a genuinely risky capability (e.g. `transfer_funds`, "
        "which is already declared risky in `config/allowlist.yaml`).\n\n"
        "Recording a real money-moving capability requires a `select_option` "
        "tool the agent doesn't have yet (ParaBank's transfer form uses "
        "`<select>` dropdowns) — see REPORT.md, Cuts.\n\n"
        f"Operator decision demonstrated here: **{decision}**.\n"
    )


print("=" * 70)
print("RUN 1 of 2 — risky capability, operator APPROVES (press Enter)")
print("=" * 70)
capability = store.load("parabank.login")
approved_dir = f"evidence/replay_risky_confirmation_approved_{ts}"
with BrowserSession(headless=False) as session:
    risky = capability.model_copy(deep=True)
    risky.risk_level = RiskLevel.RISKY
    result_approved = replay(session, risky, inputs, confirmed=False, on_escalation=to_operator)
log_replay(result_approved, approved_dir, inputs)
write_note(approved_dir, "resume")
print(f"\nSaved to {approved_dir} — status={result_approved.status.value}")

print()
print("=" * 70)
print("RUN 2 of 2 — risky capability, operator ABORTS (type 'abort')")
print("=" * 70)
aborted_dir = f"evidence/replay_risky_confirmation_aborted_{ts}"
with BrowserSession(headless=False) as session:
    risky = capability.model_copy(deep=True)
    risky.risk_level = RiskLevel.RISKY
    result_aborted = replay(session, risky, inputs, confirmed=False, on_escalation=to_operator)
log_replay(result_aborted, aborted_dir, inputs)
write_note(aborted_dir, "abort")
print(f"\nSaved to {aborted_dir} — status={result_aborted.status.value}")