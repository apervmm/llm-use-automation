import uuid
from pathlib import Path

from surface.browser import BrowserSession
from .types import EscalationRequest, OperatorDecision


# ---------- Raising an escalation ----------
def bring_to_front_quietly(session: BrowserSession) -> None:
    try:
        session.bring_to_front()
    except Exception:
        pass


def save_escalation_screenshot(session: BrowserSession, evidence_dir: str) -> str | None:
    try:
        Path(evidence_dir).mkdir(parents=True, exist_ok=True)
        path = f"{evidence_dir}/escalation_{uuid.uuid4().hex}.png"
        session.screenshot(path)
        return path
    except Exception:
        return None


# ---------- Operator prompt ----------
def print_request(request: EscalationRequest) -> None:
    print(f"Reason: {request.reason.value}")
    print(f"Task: {request.capability_or_goal}")
    print(f"Step:  {request.current_step}")
    print(f"Current URL: {request.current_url}")
    print(f"Detail: {request.detail}")


def ask_decision() -> OperatorDecision:
    """Ask until the operator types 'resume' or 'abort'"""
    while True:
        raw = input("Type 'resume' or 'abort': ").strip().lower()
        if raw == "resume":
            return OperatorDecision.RESUME
        if raw == "abort":
            return OperatorDecision.ABORT
        print("Please type exactly 'resume' or 'abort' — try again.")


def ask_note() -> list[str]:
    """An optional note"""
    note = input("Optional note for the record (press Enter to skip): ").strip()
    return [note] if note else []


def escalation_record(request: EscalationRequest, decision: OperatorDecision, human_actions: list[str]) -> dict:
    return {
        "reason": request.reason.value,
        "capability_or_goal": request.capability_or_goal,
        "current_step": request.current_step,
        "current_url": request.current_url,
        "detail": request.detail,
        "screenshot_path": request.screenshot_path,
        "timestamp": request.timestamp,
        "operator_decision": decision.value,
        "human_actions": human_actions,
    }