import re

from artifact.schema import (
    Capability, 
    Checkpoint, 
    InputParam, 
    OutcomeRule, 
    ParamType, 
    Step, 
    StepAction
)
from safety.redaction import redact_any
from surface.browser import BrowserSession
from surface.types import ActionResult
from .checkpoint import checkpoint_met
from .outcomes import ReplayStatus
from actions import Action, ActionKind, execute



PLACEHOLDER = re.compile(r"\{(\w+)\}")


# --------------- Inputs ---------------
def referenced_params(steps: list[Step]) -> set[str]:
    """Every {param} name used in a step value"""
    return {name for s in steps if s.value for name in PLACEHOLDER.findall(s.value)}


def number_errors(params: list[InputParam], inputs: dict) -> list[str]:
    """One error for each NUMBER input whose value isn't a number"""
    errors = []
    for p in params:
        if p.type == ParamType.NUMBER and p.name in inputs:
            try:
                float(inputs[p.name])
            except ValueError:
                errors.append(f"'{p.name}' must be a number, got {inputs[p.name]!r}")
    return errors


def substitute(template: str, inputs: dict) -> str:
    """Replaces every {param_name} in a step's value with the input"""
    def _sub(match):
        key = match.group(1)
        if key not in inputs:
            raise ValueError(f"Step references unknown param '{{{key}}}'")
        return str(inputs[key])
    return PLACEHOLDER.sub(_sub, template)


def fill(text: str, inputs: dict) -> str:
    """A step description with the caller's actual values in place of {placeholders}"""
    for key, val in inputs.items():
        text = text.replace("{" + key + "}", str(val))
    return text


# --------------- Running one step ---------------
def execute_step(session: BrowserSession, step: Step, value: str | None) -> ActionResult | None:
    """
        Dispatches one step to the browser
        None = nothing to execute
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


def run_step(session: BrowserSession, step: Step, value: str | None) -> ActionResult | None:
    """Executes one step, which caused a JS dialog counts as failed"""
    result = execute_step(session, step, value)
    dialogs = session.pop_dialogs()
    if dialogs and result is not None and result.success:
        result = ActionResult(
            False, 
            result.action, 
            result.target_description,
            error=f"Unexpected dialog(s) dismissed: {dialogs}"
        )
    return result


# --------------- Reading the page ---------------
def check_outcomes(session: BrowserSession, rules: list[OutcomeRule]) -> str | None:
    """The name of the first outcome rule the page matches or None"""
    session.wait(500)
    page_text = session.get_visible_text()
    for rule in rules:
        if rule.kind == "text_visible" and rule.expected in page_text:
            return rule.name
        if rule.kind == "url_contains" and rule.expected in session.get_url():
            return rule.name
    return None


def wait_for_checkpoint(session: BrowserSession, checkpoint: Checkpoint, timeout_ms: int = 5000, interval_ms: int = 250) -> bool:
    elapsed = 0
    while elapsed < timeout_ms:
        if checkpoint_met(session, checkpoint):
            return True
        session.wait(interval_ms)
        elapsed += interval_ms
    return checkpoint_met(session, checkpoint)


def account_context(session: BrowserSession, inputs: dict) -> str:
    """
        if the page already shows the account being used, include its current state, so the operator sees more than the numbers about to be submitted
    """
    account_id = inputs.get("from_account_id")
    if not account_id:
        return ""
    try:
        for line in session.get_visible_text().splitlines():
            if account_id in line:
                return f" Current state of account {account_id} shown on this page: \"{line.strip()}\""
    except Exception:
        pass
    return ""


def risky_confirmation_detail(session: BrowserSession, capability_id: str, inputs: dict) -> str:
    """
        What the operator reads before approving a risky run
        Secret inputs are redacted
    """
    params = ", ".join(f"{k}={v}" for k, v in redact_any(dict(inputs)).items())
    return f"This will run the risky capability '{capability_id}' with: {params}.{account_context(session, inputs)}"


# --------------- Outputs ---------------
def extract_outputs(capability: Capability, read_values: dict, status: ReplayStatus | None = None, outcome_name: str | None = None) -> dict:
    outputs = {}
    for f in capability.outputs:
        if f.derived_from_outcome:
            if status == ReplayStatus.SUCCESS:
                outputs[f.name] = "success"
            elif status == ReplayStatus.BUSINESS_OUTCOME:
                outputs[f.name] = outcome_name
            else:
                outputs[f.name] = None
        elif f.source_label in read_values:
            outputs[f.name] = read_values[f.source_label]
        elif "succeed" in f.name.lower() or "success" in f.name.lower():
            outputs[f.name] = "true" if status == ReplayStatus.SUCCESS else "false"
        else:
            outputs[f.name] = None
    return outputs

