from dataclasses import dataclass, field

from escalation.handoff import HandoffState
from surface.types import PageState
from .types import AgentRunResult, TranscriptStep


@dataclass
class DiscoveryRun:
    goal: str
    step_limit: int
    state: PageState
    messages: list[dict] = field(default_factory=list)
    transcript: list[TranscriptStep] = field(default_factory=list)
    outputs: dict = field(default_factory=dict)
    escalations: list[dict] = field(default_factory=list)
    handoff_state: HandoffState = field(default_factory=HandoffState)
    consecutive_failures: int = 0

    def result(self, success: bool, stop_reason: str) -> AgentRunResult:
        return AgentRunResult(self.goal, success, stop_reason, self.transcript, self.outputs, self.escalations)