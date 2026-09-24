import re
from surface.browser import BrowserSession
from artifact.schema import Capability, StepAction, Checkpoint, OutcomeRule, RiskLevel, ParamType
from escalation.handoff import raise_escalation, EscalationReason, HandoffState, OperatorDecision
from .outcomes import ReplayResult, ReplayStatus
from safety.redaction import redact_any
from replay.checkpoint import checkpoint_met
from safety.allowlist import Allowlist
from artifact.store import qualify

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


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


    handoff_state = HandoffState()
    escalations: list[dict] = [] 

    if errors := input_errors(capability, inputs):
        return ReplayResult(
            status=ReplayStatus.FAILURE,
            capability_id=capability.capability_id,
            failed_step=0, 
            expected="valid inputs", 
            observed="; ".join(errors),
            error=f"Invalid inputs: {'; '.join(errors)}",
        )

    full_id = qualify(capability.capability_id, capability.target_app)
    is_risky = capability.risk_level == RiskLevel.RISKY or Allowlist().is_risky(full_id)

    if is_risky and not confirmed:
        if on_escalation:
            safe_inputs = redact_any(dict(inputs))
            params_summary = ", ".join(f"{k}={v}" for k, v in safe_inputs.items())
            context = _try_extract_account_context(session, inputs)
            req = raise_escalation(
                session, 
                handoff_state, 
                EscalationReason.RISKY_CONFIRMATION,
                capability.capability_id,
                f"This will submit a NEW loan application with: {params_summary}.{context}",
                evidence_dir=evidence_dir,
                run_id=run_id,
            )

            decision, escalation_record = on_escalation(req, handoff_state)
            escalations.append(escalation_record)

            if decision == OperatorDecision.ABORT:
                return ReplayResult(
                    status=ReplayStatus.FAILURE, 
                    capability_id=capability.capability_id,
                    error="Replay aborted by operator during risky-confirmation escalation.",
                    escalations=escalations
                )
            
            if decision == OperatorDecision.RESUME:
                confirmed = True 

        if not confirmed:
            return ReplayResult(
                status=ReplayStatus.FAILURE,
                capability_id=capability.capability_id,
                error=(f"'{capability.capability_id}' requires confirmed=True to replay."),
                escalations=escalations
            )
        
    # _validate_inputs(capability, inputs)

    nav_result = session.goto(capability.entry_url)

    if not nav_result.success:
        return ReplayResult(
            status=ReplayStatus.FAILURE,
            capability_id=capability.capability_id,
            failed_step=0,
            expected=f"navigate to {capability.entry_url}",
            observed=nav_result.error,
            error=f"Failed to reach entry URL: {nav_result.error}",
            escalations=escalations,
        )

    read_values: dict[str, str] = {}
    step_index = 0
    # steps = capability.steps
    steps = sorted(capability.steps, key=lambda s: s.step_num)  


    # for step in capability.steps:
    while step_index < len(steps):
        step = steps[step_index]
        value = _substitute(step.value, inputs) if step.value else None
        result = _execute_step(session, step, value)

        if result is not None and result.policy_violation:
            return ReplayResult(
                status=ReplayStatus.FAILURE,
                capability_id=capability.capability_id,
                failed_step=step.step_num,
                expected=step.description,
                observed=result.error,
                error=f"Policy violation at step {step.step_num}: {result.error}",
                escalations=escalations,
            )

        # if step.action == StepAction.READ:
        #     if result is not None and result.success:
        #         read_values[step.read_label] = result.value
        #     step_index += 1
        #     continue

        if step.action == StepAction.READ:
            if step.target is None:
                step_index += 1
                continue
            if result is not None and result.success:
                read_values[step.read_label] = result.value
                step_index += 1
                continue

        if result is None or not result.success:
            error_text = result.error if result else "no action executed"

            outcome = _check_outcomes(session, capability.outcome_rules)
            if outcome:
                return ReplayResult(
                    status=ReplayStatus.BUSINESS_OUTCOME,
                    capability_id=capability.capability_id,
                    outcome_name=outcome,
                    outputs=_extract_outputs(capability, read_values, status=ReplayStatus.BUSINESS_OUTCOME, outcome_name=outcome),
                    escalations=escalations,
                )
            if on_escalation:
                req = raise_escalation(
                    session, 
                    handoff_state, 
                    EscalationReason.REPLAY_FAILURE,
                    capability.capability_id,
                    f"Step {step.step_num} ({step.action.value}) failed: {error_text}",
                    current_step=step.step_num,
                )


                decision, escalation_record = on_escalation(req, handoff_state)
                escalations.append(escalation_record)
                


                if decision == OperatorDecision.RESUME:
                    retry_result = _execute_step(session, step, value)
                    if retry_result is not None and retry_result.success:
                        step_index += 1
                        continue
                    
                    outcome = _check_outcomes(session, capability.outcome_rules)
                    if outcome:
                        return ReplayResult(
                            status=ReplayStatus.BUSINESS_OUTCOME,
                            capability_id=capability.capability_id,
                            outcome_name=outcome,
                            outputs=_extract_outputs(capability, read_values, status=ReplayStatus.BUSINESS_OUTCOME, outcome_name=outcome),
                            escalations=escalations,
                        )
                    

                    retry_error = retry_result.error if retry_result else error_text

                    return ReplayResult(
                        status=ReplayStatus.FAILURE,
                        capability_id=capability.capability_id,
                        failed_step=step.step_num,
                        expected=step.description,
                        observed=retry_error,
                        error=f"Step {step.step_num} ({step.action.value}) failed even after operator intervention: {retry_error}",
                        escalations=escalations,
                    )
            return ReplayResult(
                status=ReplayStatus.FAILURE,
                capability_id=capability.capability_id,
                failed_step=step.step_num,
                expected=step.description,
                observed=error_text,
                error=f"Step {step.step_num} ({step.action.value}) failed: {error_text}",
                escalations=escalations,
            )

        step_index += 1  



    if capability.checkpoint and not _wait_for_checkpoint(session, capability.checkpoint):
        outcome = _check_outcomes(session, capability.outcome_rules)
        if outcome:
            return ReplayResult(
                status=ReplayStatus.BUSINESS_OUTCOME,
                capability_id=capability.capability_id,
                outcome_name=outcome,
                outputs=_extract_outputs(capability, read_values, status=ReplayStatus.BUSINESS_OUTCOME, outcome_name=outcome),
                escalations=escalations,
            )
        

        if on_escalation:
            req = raise_escalation(
                session,
                handoff_state,
                EscalationReason.REPLAY_FAILURE,
                capability.capability_id,
                f"Checkpoint not met: {capability.checkpoint.kind}={capability.checkpoint.expected}",
                current_step=steps[-1].step_num if steps else None,
            )
            
            decision, escalation_record = on_escalation(req, handoff_state)
            escalations.append(escalation_record)

            if decision == OperatorDecision.RESUME and _wait_for_checkpoint(session, capability.checkpoint):
                outputs = _extract_outputs(capability, read_values, status=ReplayStatus.SUCCESS)
                return ReplayResult(
                    status=ReplayStatus.SUCCESS, 
                    capability_id=capability.capability_id, 
                    outputs=outputs,
                    escalations=escalations,
                )



        return ReplayResult(
            status=ReplayStatus.FAILURE,
            capability_id=capability.capability_id,
            failed_step=steps[-1].step_num if steps else None,
            expected=f"{capability.checkpoint.kind}={capability.checkpoint.expected}",
            observed=session.get_url(),
            error="Checkpoint not met and no matching business outcome found.",
            escalations=escalations,
        )
    

    outputs = _extract_outputs(capability, read_values, status=ReplayStatus.SUCCESS)
    return ReplayResult(
        status=ReplayStatus.SUCCESS, 
        capability_id=capability.capability_id, 
        outputs=outputs,
        escalations=escalations,
    )


# def _validate_inputs(capability: Capability, inputs: dict) -> None:
#     missing = [p.name for p in capability.inputs if p.required and p.name not in inputs]
#     if missing:
#         raise ValueError(f"Missing required input(s): {missing}")


def input_errors(capability: Capability, inputs: dict) -> list[str]:
    declared = {p.name for p in capability.inputs}
    referenced = {m for s in capability.steps if s.value for m in _PLACEHOLDER.findall(s.value)}
    missing = sorted(p.name for p in capability.inputs if p.required and p.name not in inputs)
    errors = []
    if missing:
        errors.append(f"missing required input(s): {missing}")
    if unknown := sorted(set(inputs) - declared):
        errors.append(f"unknown input(s): {unknown}")
    if unsupplied := sorted(referenced - set(inputs) - set(missing)):
        errors.append(f"steps reference params with no value: {unsupplied}")

    for p in capability.inputs:
           if p.type == ParamType.NUMBER and p.name in inputs:
               try:
                   float(inputs[p.name])
               except ValueError:
                   errors.append(f"'{p.name}' must be a number, got {inputs[p.name]!r}")

    return errors


def _substitute(template: str, inputs: dict) -> str:
    """Replace every {param_name} in a step's value with the supplied input"""
    def _sub(match):
        key = match.group(1)
        if key not in inputs:
            raise ValueError(f"Step references unknown param '{{{key}}}'")
        return str(inputs[key])
    return re.sub(r"\{(\w+)\}", _sub, template)


def _check_outcomes(session: BrowserSession, rules: list[OutcomeRule]) -> str | None:
    session.wait(500)
    page_text = session.get_visible_text()
    for rule in rules:
        if rule.kind == "text_visible" and rule.expected in page_text:
            return rule.name
        if rule.kind == "url_contains" and rule.expected in session.get_url():
            return rule.name
    return None


def _extract_outputs(
    capability: Capability, 
    read_values: dict,
    status: ReplayStatus | None = None,
    outcome_name: str | None = None
) -> dict:
    outputs = {}
    for field in capability.outputs:
        if field.derived_from_outcome:
            if status == ReplayStatus.SUCCESS:
                outputs[field.name] = "Approved"
            elif status == ReplayStatus.BUSINESS_OUTCOME:
                outputs[field.name] = "Denied"
            else:
                outputs[field.name] = None
        elif field.source_label in read_values:
            outputs[field.name] = read_values[field.source_label]
        elif "succeed" in field.name.lower() or "success" in field.name.lower():
            outputs[field.name] = "true" if status == ReplayStatus.SUCCESS else "false"
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
        if checkpoint_met(session, checkpoint):
            return True
        session.wait(interval_ms)
        elapsed += interval_ms
    return checkpoint_met(session, checkpoint)



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
    if step.action == StepAction.SELECT_OPTION:
        return session.select_option(step.target, value, description=step.description)
    if step.action == StepAction.READ:
        if step.target is None:
            return None
        return session.read_text(step.target, description=step.description)
    return None


def _try_extract_account_context(session: BrowserSession, inputs: dict) -> str:
    """Best-effort: if the current page already shows account balances (e.g.
    we just came from Accounts Overview) and the inputs reference an
    account, surface that account's real current state — not just the
    numbers being submitted, which alone say nothing about whether they're
    reasonable."""
    account_id = inputs.get("from_account_id")
    if not account_id:
        return ""
    try:
        text = session.get_visible_text()
        for line in text.splitlines():
            if account_id in line:
                return f" Current state of account {account_id} shown on this page: \"{line.strip()}\""
    except Exception:
        pass
    return ""