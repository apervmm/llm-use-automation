from surface.browser import BrowserSession

from .helpers import bring_to_front_quietly, save_escalation_screenshot
from .types import EscalationReason, EscalationRequest, HandoffState, OperatorDecision


__all__ = [
    "raise_escalation", 
    "EscalationReason", 
    "EscalationRequest", 
    "HandoffState", 
    "OperatorDecision"
]


def raise_escalation(
    session: BrowserSession,
    state: HandoffState,
    reason: EscalationReason,
    capability_or_goal: str,
    detail: str, 
    current_step: int | None = None,
    evidence_dir: str = "evidence/escalations",
    run_id: str | None = None, 
) -> EscalationRequest:
    bring_to_front_quietly(session)
    screenshot_path = save_escalation_screenshot(session, evidence_dir)
    state.transfer_to_human()

    return EscalationRequest(
        reason=reason,
        capability_or_goal=capability_or_goal,
        current_step=current_step,
        current_url=session.get_url(),
        detail=detail,
        screenshot_path=screenshot_path,
        run_id=run_id, 
        # evidence_dir=evidence_dir,
    )