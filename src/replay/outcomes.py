from dataclasses import dataclass, field
from enum import Enum


class ReplayStatus(str, Enum):
    SUCCESS = "success"  # checkpoint met, outputs returned
    BUSINESS_OUTCOME = "business_outcome"  # expected non-success res
    FAILURE = "failure" # unexpected debuggable fail


@dataclass
class ReplayResult:
    status: ReplayStatus
    capability_id: str
    outputs: dict = field(default_factory=dict)
    outcome_name: str | None = None     # status == BUSINESS_OUTCOME
    failed_step: int | None = None       # sstatus == FAILURE
    expected: str | None = None
    observed: str | None = None
    error: str | None = None