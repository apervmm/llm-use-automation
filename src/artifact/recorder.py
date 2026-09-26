from agent.loop import AgentRunResult
from safety.allowlist import Allowlist
from .schema import (
    Capability, 
    Checkpoint, 
    RiskLevel, 
)
from .helpers import build_inputs, build_outputs, build_steps, template, unmatched_params
from .store import qualify



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
    outcome_derived_outputs = outcome_derived_outputs or []

    steps = build_steps(run_result.transcript, param_map)
    if unmatched := unmatched_params(steps, param_map):
        raise ValueError(
            f"Param(s) {unmatched} never matched a typed/selected value - check the env vars are set and the goal uses the same literals"
        )
    

    full_id = qualify(capability_id)
    risk_level = RiskLevel.RISKY if allowlist.is_risky(full_id) else RiskLevel.SAFE

    return Capability(
        capability_id=full_id,
        description=template(description or f"Recorded capability for goal: {run_result.goal}", param_map),
        entry_url=entry_url,
        inputs=build_inputs(param_map),
        outputs=build_outputs(output_keys, run_result.outputs, outcome_derived_outputs),
        steps=steps,
        checkpoint=checkpoint,
        risk_level=risk_level,
    )

