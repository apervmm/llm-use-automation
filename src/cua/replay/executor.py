import re
from cua.surface.browser import BrowserSession
from cua.surface.perception import snapshot
from cua.artifact.schema import Capability, StepAction, Checkpoint, OutcomeRule, RiskLevel
from cua.escalation.handoff import raise_escalation, EscalationReason, HandoffState, OperatorDecision
from .outcomes import ReplayResult, ReplayStatus


def replay(
    session: BrowserSession, 
    capability: Capability, 
    inputs: dict, 
    confirmed: bool = False,
    on_escalation=None,
) -> ReplayResult:
    """
    Execute a saved Capability deterministically, using the provided inputs to fill in any parameterized values.
    
    Checkpoint miss => checks declared outcome_rules before concluding it's a hard failure.
    """
    handoff_state = HandoffState()

    if capability.risk_level == RiskLevel.RISKY and not confirmed:
        if on_escalation:
            req = raise_escalation(
                session, 
                handoff_state, 
                EscalationReason.RISKY_CONFIRMATION,
                capability.capability_id,
                "Risky capability requires explicit confirmation before unattended replay.",
            )

            decision = on_escalation(req, handoff_state)

            if decision == OperatorDecision.ABORT:
                return ReplayResult(
                    status=ReplayStatus.FAILURE, 
                    capability_id=capability.capability_id,
                    error="Replay aborted by operator during risky-confirmation escalation."
                )
            
            if decision == OperatorDecision.RESUME:
                confirmed = True 

        if not confirmed:
            return ReplayResult(
                status=ReplayStatus.FAILURE,
                capability_id=capability.capability_id,
                error=(
                    f"'{capability.capability_id}' requires confirmed=True to replay."
                ),
            )
        
    _validate_inputs(capability, inputs)

    nav_result = session.goto(capability.entry_url)

    if not nav_result.success:
        return ReplayResult(
            status=ReplayStatus.FAILURE,
            capability_id=capability.capability_id,
            failed_step=0,
            expected=f"navigate to {capability.entry_url}",
            observed=nav_result.error,
            error=f"Failed to reach entry URL: {nav_result.error}",
        )

    read_values: dict[str, str] = {}
    step_index = 0
    steps = capability.steps


    # for step in capability.steps:
    while step_index < len(steps):
        step = steps[step_index]
        value = _substitute(step.value, inputs) if step.value else None
        result = _execute_step(session, step, value)

        if step.action == StepAction.NAVIGATE:
            result = session.goto(value)
        elif step.action == StepAction.CLICK:
            result = session.click(step.target, description=step.description)
        elif step.action == StepAction.TYPE_TEXT:
            result = session.type_text(step.target, value, description=step.description)
        elif step.action == StepAction.READ:
            if step.target is None:
                continue 
            result = session.read_text(step.target, description=step.description)
            if result.success:
                read_values[step.read_label] = result.value
            continue 
        else:
            continue  # READ steps don't act on the browser

        if not result.success:
            outcome = _check_outcomes(session, capability.outcome_rules)
            if outcome:
                return ReplayResult(
                    status=ReplayStatus.BUSINESS_OUTCOME,
                    capability_id=capability.capability_id,
                    outcome_name=outcome,
                )
            if on_escalation:
                req = raise_escalation(
                    session, 
                    handoff_state, 
                    EscalationReason.REPLAY_FAILURE,
                    capability.capability_id,
                    f"Step {step.step_num} ({step.action}) failed: {result.error}",
                    current_step=step.step_num,
                )
                decision = on_escalation(req, handoff_state)

            return ReplayResult(
                status=ReplayStatus.FAILURE,
                capability_id=capability.capability_id,
                failed_step=step.step_num,
                expected=step.description,
                observed=result.error,
                error=f"Step {step.step_num} ({step.action}) failed: {result.error}",
            )
        
    if capability.checkpoint and not _wait_for_checkpoint(session, capability.checkpoint):
        outcome = _check_outcomes(session, capability.outcome_rules)
        if outcome:
            return ReplayResult(
                status=ReplayStatus.BUSINESS_OUTCOME,
                capability_id=capability.capability_id,
                outcome_name=outcome,
            )
        return ReplayResult(
            status=ReplayStatus.FAILURE,
            capability_id=capability.capability_id,
            failed_step=capability.steps[-1].step_num if capability.steps else None,
            expected=f"{capability.checkpoint.kind}={capability.checkpoint.expected}",
            observed=session.page.url,
            error="Checkpoint not met and no matching business outcome found.",
        )

    outputs = _extract_outputs(capability, read_values)
    return ReplayResult(status=ReplayStatus.SUCCESS, capability_id=capability.capability_id, outputs=outputs)


def _validate_inputs(capability: Capability, inputs: dict) -> None:
    missing = [p.name for p in capability.inputs if p.required and p.name not in inputs]
    if missing:
        raise ValueError(f"Missing required input(s): {missing}")


def _substitute(template: str, inputs: dict) -> str:
    """Replace every {param_name} in a step's value with the supplied input"""
    def _sub(match):
        key = match.group(1)
        if key not in inputs:
            raise ValueError(f"Step references unknown param '{{{key}}}'")
        return str(inputs[key])
    return re.sub(r"\{(\w+)\}", _sub, template)


def _checkpoint_met(session: BrowserSession, checkpoint: Checkpoint) -> bool:
    if checkpoint.kind == "url_contains":
        return checkpoint.expected in session.page.url
    if checkpoint.kind == "text_visible":
        return checkpoint.expected in session.page.inner_text("body")
    if checkpoint.kind == "element_visible":
        return session.page.locator(checkpoint.expected).first.is_visible()
    return False


def _check_outcomes(session: BrowserSession, rules: list[OutcomeRule]) -> str | None:
    session.page.wait_for_timeout(500)
    page_text = session.page.inner_text("body")
    for rule in rules:
        if rule.kind == "text_visible" and rule.expected in page_text:
            return rule.name
        if rule.kind == "url_contains" and rule.expected in session.page.url:
            return rule.name
    return None


def _extract_outputs(capability: Capability, read_values: dict) -> dict:
    outputs = {}
    for field in capability.outputs:
        if field.source_label in read_values:
            outputs[field.name] = read_values[field.source_label]
        elif "succeed" in field.name.lower() or "success" in field.name.lower():
            outputs[field.name] = "true"
        else:
            outputs[field.name] = None
    return outputs


def _wait_for_checkpoint(
        session: BrowserSession, 
        checkpoint: Checkpoint, 
        timeout_ms: int = 5000, 
        interval_ms: int = 250
    ) -> bool:
    """Poll instead of a single point-in-time check — async redirects/renders
    can legitimately take a moment after the triggering action completes."""
    elapsed = 0
    while elapsed < timeout_ms:
        if _checkpoint_met(session, checkpoint):
            return True
        session.page.wait_for_timeout(interval_ms)
        elapsed += interval_ms
    return _checkpoint_met(session, checkpoint)



def _execute_step(session: BrowserSession, step, value: str | None):
    """
        Dispatches one step to the browser
        Returns an ActionResult, or None if there was nothing to execute 
    """
    if step.action == StepAction.NAVIGATE:
        return session.goto(value)
    if step.action == StepAction.CLICK:
        return session.click(step.target, description=step.description)
    if step.action == StepAction.TYPE_TEXT:
        return session.type_text(step.target, value, description=step.description)
    if step.action == StepAction.READ:
        if step.target is None:
            return None
        return session.read_text(step.target, description=step.description)
    return None