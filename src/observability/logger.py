from pathlib import Path

from agent.loop import AgentRunResult
from replay.outcomes import ReplayResult
from safety.redaction import redact_any
from .utils import account_values, discovery_account_values, timestamp, to_jsonable, write_summary


def log_discovery(
    result: AgentRunResult, 
    evidence_dir: str, 
    sensitive_values: list[str] | None = None, 
    run_id: str | None = None
) -> Path:
    """
        Writes a structured summary of a discovery run alongside the screenshots AgentLoop already saved into evidence_dir
    """
    summary = {
        "run_type": "discovery",
        "run_id": run_id,
        "timestamp": timestamp(),
        "goal": result.goal,
        "success": result.success,
        "stop_reason": result.stop_reason,
        "escalations": result.escalations,
        "outputs": result.outputs,
        "transcript": [to_jsonable(step) for step in result.transcript],
    }

    safe = redact_any(
        summary, 
        sensitive_values=set(sensitive_values or []),
        masked_values=discovery_account_values(result)
    )
    return write_summary(evidence_dir, safe)


def log_replay(
    result: ReplayResult, 
    evidence_dir: str, 
    inputs: dict,
    run_id: str | None = None
) -> Path:
    """
        Writes a structured summary of a single replay invocation
    """
    summary = {
        "run_type": "replay",
        "run_id": run_id,
        "timestamp": timestamp(),
        "inputs": {k: ("[REDACTED]" if "password" in k.lower() else v) for k, v in inputs.items()},
        "status": result.status.value,
        "capability_id": result.capability_id,
        "outputs": result.outputs,
        "outcome_name": result.outcome_name,
        "failed_step": result.failed_step,
        "expected": result.expected,
        "observed": result.observed,
        "error": result.error,
        "escalations": result.escalations,
    }
    secrets = {str(v) for k, v in inputs.items() if k.lower() in ("password", "pin", "ssn") and v}
    accounts = account_values({**inputs, **(result.outputs or {})})
    safe = redact_any(summary, sensitive_values=secrets, masked_values=accounts)
    return write_summary(evidence_dir, safe)