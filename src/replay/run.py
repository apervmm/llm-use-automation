from dataclasses import dataclass, field
from typing import Callable

from artifact.schema import Capability, Step
from escalation.handoff import EscalationReason, HandoffState, OperatorDecision, raise_escalation
from surface.browser import BrowserSession
from surface.types import ActionResult
from .helpers import extract_outputs, fill
from .outcomes import ReplayResult, ReplayStatus


@dataclass
class ReplayRun:
    """one replay carries between its phases +  how it builds its results"""
    session: BrowserSession
    capability: Capability
    inputs: dict
    on_escalation: Callable | None = None
    run_id: str | None = None
    evidence_dir: str = "evidence/escalations"
    handoff_state: HandoffState = field(default_factory=HandoffState)
    escalations: list[dict] = field(default_factory=list)
    read_values: dict[str, str] = field(default_factory=dict)


    @property
    def capability_id(self) -> str:
        return self.capability.capability_id


    def escalate(self, reason: EscalationReason, detail: str, current_step: int | None = None) -> OperatorDecision | None:
        """Ask the operator and record the escalation. None when there's no operator to ask."""
        if not self.on_escalation:
            return None
        request = raise_escalation(
            self.session, self.handoff_state, reason, self.capability_id, detail,
            current_step=current_step, evidence_dir=self.evidence_dir, run_id=self.run_id,
        )
        decision, record = self.on_escalation(request, self.handoff_state)
        self.escalations.append(record)
        return decision


    def success(self) -> ReplayResult:
        return ReplayResult(
            status=ReplayStatus.SUCCESS,
            capability_id=self.capability_id,
            outputs=extract_outputs(self.capability, self.read_values, status=ReplayStatus.SUCCESS),
            escalations=self.escalations,
        )


    def business_outcome(self, outcome_name: str) -> ReplayResult:
        return ReplayResult(
            status=ReplayStatus.BUSINESS_OUTCOME,
            capability_id=self.capability_id,
            outcome_name=outcome_name,
            outputs=extract_outputs(
                self.capability,
                self.read_values,
                status=ReplayStatus.BUSINESS_OUTCOME, 
                outcome_name=outcome_name
            ),
            escalations=self.escalations,
        )


    def failure(self, error: str, failed_step: int | None = None,
                expected: str | None = None, observed: str | None = None) -> ReplayResult:
        return ReplayResult(
            status=ReplayStatus.FAILURE,
            capability_id=self.capability_id,
            failed_step=failed_step,
            expected=expected,
            observed=observed,
            error=error,
            escalations=self.escalations,
        )


    def step_failure(self, step: Step, observed: str, error: str) -> ReplayResult:
        return self.failure(
            error, 
            failed_step=step.step_num,
            expected=fill(step.description, self.inputs), 
            observed=observed
        )


    def policy_failure(self, step: Step, result: ActionResult) -> ReplayResult:
        return self.step_failure(step, result.error, f"Policy violation at step {step.step_num}: {result.error}")