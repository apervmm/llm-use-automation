from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class OperatorDecision(str, Enum):
    RESUME = "resume" # hand control back to automation
    ABORT = "abort"  # stop the run


class EscalationReason(str, Enum):
    DISCOVERY_STUCK = "discovery_stuck"  # hit max steps or repeated failures
    REPLAY_FAILURE = "replay_failure"     # a step or the checkpoint failed
    RISKY_CONFIRMATION = "risky_confirmation"  # a risky capability needs approval


@dataclass
class EscalationRequest:
    reason: EscalationReason
    capability_or_goal: str
    current_step: int | None
    current_url: str
    detail: str
    screenshot_path: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    run_id: str | None = None


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