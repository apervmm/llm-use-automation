from surface.browser import BrowserSession
from artifact.schema import Capability, StepAction, Step, RiskLevel
from escalation.handoff import EscalationReason, OperatorDecision
from .outcomes import ReplayResult
from safety.allowlist import Allowlist
from artifact.store import qualify
from .helpers import (
    check_outcomes,
    number_errors,
    referenced_params,
    risky_confirmation_detail,
    run_step,
    substitute,
    wait_for_checkpoint,
)
from .run import ReplayRun


def replay(
    session: BrowserSession, 
    capability: Capability, 
    inputs: dict, 
    confirmed: bool = False,
    on_escalation=None,
    run_id: str | None = None,
    evidence_dir: str = "evidence/escalations",
) -> ReplayResult:
    """
    Execute a saved Capability deterministically, using the provided inputs to fill in any parameterized values.
    
    Checkpoint miss => checks declared outcome_rules before concluding it's a hard failure.
    """
    run = ReplayRun(session, capability, inputs, on_escalation, run_id, evidence_dir)
    if errors := input_errors(capability, inputs):
        joined = "; ".join(errors)
        return run.failure(f"Invalid inputs: {joined}", failed_step=0, expected="valid inputs", observed=joined)

    if _is_risky(capability) and not confirmed:
        if refusal := _confirm_risky_run(run):
            return refusal
        
    nav = session.goto(capability.entry_url)
    if not nav.success:
        return run.failure(
            f"Failed to reach entry URL: {nav.error}", 
            failed_step=0,
            expected=f"navigate to {capability.entry_url}", 
            observed=nav.error
        )

    steps = sorted(capability.steps, key=lambda s: s.step_num)
    for step in steps:
        if final := _run_step_with_recovery(run, step):
            return final

    return _conclude(run, last_step=steps[-1].step_num if steps else None)


def input_errors(capability: Capability, inputs: dict) -> list[str]:
    declared = {p.name for p in capability.inputs}
    missing = sorted(p.name for p in capability.inputs if p.required and p.name not in inputs)
    errors = []
    if missing:
        errors.append(f"missing required input(s): {missing}")
    if unknown := sorted(set(inputs) - declared):
        errors.append(f"unknown input(s): {unknown}")
    if unsupplied := sorted(referenced_params(capability.steps) - set(inputs) - set(missing)):
        errors.append(f"steps reference params with no value: {unsupplied}")
    errors.extend(number_errors(capability.inputs, inputs))
    return errors


def _is_risky(capability: Capability) -> bool:
    full_id = qualify(capability.capability_id, capability.target_app)
    return capability.risk_level == RiskLevel.RISKY or Allowlist().is_risky(full_id)


def _confirm_risky_run(run: ReplayRun) -> ReplayResult | None:
    """ 
        A risky run needs the operator's go-ahead before step 1
        Returns a failure or None to proceed
    """
    if run.on_escalation:
        decision = run.escalate(
            EscalationReason.RISKY_CONFIRMATION,
            risky_confirmation_detail(run.session, run.capability_id, run.inputs)
        )
        if decision == OperatorDecision.ABORT:
            return run.failure("Replay aborted by operator during risky-confirmation escalation.")
        if decision == OperatorDecision.RESUME:
            return None
    return run.failure(f"'{run.capability_id}' requires confirmed=True to replay.")



def _run_step_with_recovery(run: ReplayRun, step: Step) -> ReplayResult | None:
    """
    Run one step. Returns a final result if the run ends here, or None to continue

    On failure: a policy violation stops at once
    a matching outcome rule ends the run as BUSINESS_OUTCOME
    otherwise the operator is asked, and on resume the step is retried
    """
    value = substitute(step.value, run.inputs) if step.value else None
    result = run_step(run.session, step, value)

    if result is not None and result.policy_violation:
        return run.policy_failure(step, result)

    if step.action == StepAction.READ:
        if step.target is None:
            return None  
        if result is not None and result.success:
            run.read_values[step.read_label] = result.value
            return None

    if result is not None and result.success:
        return None

    error_text = result.error if result else "no action executed"
    if outcome := check_outcomes(run.session, run.capability.outcome_rules):
        return run.business_outcome(outcome)

    decision = run.escalate(
        EscalationReason.REPLAY_FAILURE,
        f"Step {step.step_num} ({step.action.value}) failed: {error_text}",
        current_step=step.step_num
    )
    if decision == OperatorDecision.RESUME:
        return _retry_after_operator(run, step, value, error_text)

    return run.step_failure(step, error_text, f"Step {step.step_num} ({step.action.value}) failed: {error_text}")


def _retry_after_operator(run: ReplayRun, step: Step, value: str | None, first_error: str) -> ReplayResult | None:
    run.session.pop_dialogs() 
    retry = run_step(run.session, step, value)

    if retry is not None and retry.policy_violation:
        return run.policy_failure(step, retry)
    if retry is not None and retry.success:
        if step.action == StepAction.READ:
            run.read_values[step.read_label] = retry.value
        return None
    if outcome := check_outcomes(run.session, run.capability.outcome_rules):
        return run.business_outcome(outcome)

    error = retry.error if retry else first_error
    return run.step_failure(
        step, 
        error,
        f"Step {step.step_num} ({step.action.value}) failed even after operator intervention: {error}"
    )


def _conclude(run: ReplayRun, last_step: int | None) -> ReplayResult:
    """
    After the last step: 
    SUCCESS if the checkpoint is met
    else BUSINESS_OUTCOME if an outcome rule matches
    else ask the operator before FAILURE
    """
    checkpoint = run.capability.checkpoint
    if not checkpoint or wait_for_checkpoint(run.session, checkpoint):
        return run.success()

    if outcome := check_outcomes(run.session, run.capability.outcome_rules):
        return run.business_outcome(outcome)

    expected = f"{checkpoint.kind}={checkpoint.expected}"
    decision = run.escalate(
        EscalationReason.REPLAY_FAILURE, 
        f"Checkpoint not met: {expected}",
        current_step=last_step
    )
    if decision == OperatorDecision.RESUME and wait_for_checkpoint(run.session, checkpoint):
        return run.success()

    return run.failure(
        "Checkpoint not met and no matching business outcome found.",
        failed_step=last_step, 
        expected=expected, 
        observed=run.session.get_url()
    )