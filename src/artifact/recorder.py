from agent.loop import AgentRunResult, TranscriptStep
from .schema import (
    Capability, 
    Step, 
    StepAction, 
    InputParam, 
    OutputField, 
    Checkpoint, 
    RiskLevel, 
    ParamType
)
from safety.allowlist import Allowlist
from safety.redaction import redact
from .store import qualify

import re


def record(
    run_result: AgentRunResult,
    capability_id: str,
    entry_url: str,
    param_map: dict[str, str],
    output_keys: list[str],
    checkpoint: Checkpoint,
    description: str = "",
    allowlist: Allowlist | None = None,
    outcome_derived_outputs: list[str] | None = None, 
) -> Capability:
    if not run_result.success:
        raise ValueError("Cannot record a capability from a failed run.")

    allowlist = allowlist or Allowlist()
    steps = _build_steps(run_result.transcript, param_map)

    unmatched = [name for name in param_map.values() if not any(s.value and f"{{{name}}}" in s.value for s in steps)]
    if unmatched: 
        raise ValueError(
            f"Param(s) {unmatched} never matched a typed/selected value - check the env vars are set and the goal uses the same literals.")
    description = _template(description or f"Recorded capability for goal: {run_result.goal}", param_map)

    inputs = [
        InputParam(
            name=name, 
            type=_infer_type(literal),
            example="[REDACTED]" if name.lower() in ("password", "pin", "ssn") else literal
        )
        for literal, name in param_map.items()
    ]

    outcome_derived_outputs = outcome_derived_outputs or []

    outputs = [
        OutputField(
            name=key,
            source_label=key,
            derived_from_outcome=(key in outcome_derived_outputs),
        )
        for key in output_keys
        if key in run_result.outputs or key in outcome_derived_outputs
    ]

    full_id = qualify(capability_id)
    risk_level = RiskLevel.RISKY if allowlist.is_risky(full_id) else RiskLevel.SAFE

    return Capability(
        capability_id=full_id,
        description=description or f"Recorded capability for goal: {run_result.goal}",
        entry_url=entry_url,
        inputs=inputs,
        outputs=outputs,
        steps=steps,
        checkpoint=checkpoint,
        risk_level=risk_level,
    )


def _build_steps(transcript: list[TranscriptStep], param_map: dict[str, str]) -> list[Step]:
    steps: list[Step] = []
    step_num = 1

    for t in transcript:
        if not t.success or t.tool_name == "done":
            continue

        if t.tool_name == "read":
            steps.append(Step(
                step_num=step_num, action=StepAction.READ,
                target=t.resolved_ref, # None if the LLM didn't name an element
                read_label=t.tool_input.get("label"),
                description=f"Read '{t.tool_input.get('label')}'",
            ))
        elif t.tool_name == "click":
            steps.append(Step(
                step_num=step_num,
                action=StepAction.CLICK,
                target=t.resolved_ref,
                description=f"Click '{t.tool_input.get('element_name')}'",
            ))

        elif t.tool_name == "type_text":
            literal = t.tool_input.get("text", "")
            value = _parameterize(literal, param_map)
            steps.append(Step(
                step_num=step_num,
                action=StepAction.TYPE_TEXT,
                target=t.resolved_ref,
                value=value,
                description=f"Type into '{t.tool_input.get('element_name')}'",
            ))
        elif t.tool_name == "select_option":
            literal = t.tool_input.get("option_value", "")
            value = _parameterize(literal, param_map)
            steps.append(Step(
                step_num=step_num,
                action=StepAction.SELECT_OPTION,
                target=t.resolved_ref,
                value=value,
                description=f"Select '{t.tool_input.get('option_value')}' in '{t.tool_input.get('element_name')}'",
            ))
        elif t.tool_name == "navigate":
            steps.append(Step(
                step_num=step_num,
                action=StepAction.NAVIGATE,
                value=t.tool_input.get("url"),
                description=f"Navigate to {t.tool_input.get('url')}",
            ))

        else:
            continue

        step_num += 1

    return steps


def _parameterize(literal: str, param_map: dict[str, str]) -> str:
    return f"{{{param_map[literal]}}}" if literal in param_map else literal


def _template(text: str, param_map: dict[str, str]) -> str:
    """Replace recorded literals with {param} placeholders, longest first."""
    for literal in sorted(param_map, key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(literal)}(?!\w)", "{" + param_map[literal] + "}", text)
    return text


def _infer_type(literal: str) -> ParamType:
    """'1000' -> NUMBER, 'demo' -> STRING, based on the value the agent actually used."""
    try:
        float(literal)
        return ParamType.NUMBER
    except ValueError:
        return ParamType.STRING