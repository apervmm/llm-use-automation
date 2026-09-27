from dataclasses import dataclass, field
from surface.types import ElementRef


@dataclass
class TranscriptStep:
    step_num: int
    page_url: str
    tool_name: str
    tool_input: dict
    success: bool
    detail: str
    screenshot_path: str | None = None
    resolved_ref: ElementRef | None = None


@dataclass
class AgentRunResult:
    goal: str
    success: bool
    stop_reason: str
    transcript: list[TranscriptStep] = field(default_factory=list)
    outputs: dict = field(default_factory=dict)
    escalations: list[dict] = field(default_factory=list)