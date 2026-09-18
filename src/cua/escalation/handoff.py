
from enum import Enum
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
import uuid

from cua.surface.browser import BrowserSession



class OperatorDecision(str, Enum):
    RESUME = "resume"  # human stops
    ABORT = "abort"   # human aborts


class EscalationReason(str, Enum):
    DISCOVERY_STUCK = "discovery_stuck" # hitting max step, no tooling, or dead-end
    REPLAY_FAILURE = "replay_failure"      # unrecoverable replay failure
    RISKY_CONFIRMATION = "risky_confirmation" 


@dataclass
class EscalationRequest:
    reason: EscalationReason
    capability_or_goal: str
    current_step: int
    current_url: str
    detail: str
    screenshot_path: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class HandoffState:
    def __init__(self):
        self.automation_in_control = True
        self.human_actions_log: list[str] = []

    def transfer_to_human(self):
        self.automation_in_control = False

    def resume_automation(self):
        self.automation_in_control = True

    def record_human_action(self, description: str):
        self.human_actions_log.append(description)




def raise_escalation(
    session: BrowserSession,
    state: HandoffState,
    reason: EscalationReason,
    capability_or_goal: str,
    detail: str, 
    current_step: int | None = None,
    evidence_dir: str = "evidence/escalations",
) -> EscalationRequest:
    
    try:
        session.page.bring_to_front()
    except Exception:
        pass
    
    screenshot_path = None

    try:
        Path(evidence_dir).mkdir(parents=True, exist_ok=True)
        screenshot_path = f"{evidence_dir}/escalation_{uuid.uuid4().hex}.png"
        session.screenshot(screenshot_path)
    except Exception:
        screenshot_path = None  



    state.transfer_to_human()

    return EscalationRequest(
        reason=reason,
        capability_or_goal=capability_or_goal,
        current_step=current_step,
        current_url=session.page.url,
        detail=detail,
        screenshot_path=screenshot_path,
    )