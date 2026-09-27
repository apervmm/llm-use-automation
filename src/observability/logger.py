import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path

from agent.loop import AgentRunResult
from replay.outcomes import ReplayResult
from safety.redaction import redact_any
from .helpers import account_values, discovery_account_values, timestamp, to_jsonable, write_summary

def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _to_jsonable(obj):
    """
        Recursively converts dataclasses into plain JSON-serializable data
    """
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if hasattr(obj, "value") and hasattr(obj, "name") and not isinstance(obj, (str, int)):
        return obj.value  # Enum
    if isinstance(obj, list):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    return obj


def _discovery_account_values(result) -> set[str]:
    values = {str(v) for k, v in (result.outputs or {}).items() if "account" in k.lower() and str(v).isdigit()}
    for step in result.transcript:
        inp = step.tool_input or {}
        if "account" in str(inp.get("element_name", "")).lower():
            for key in ("option_value", "text"):
                if str(inp.get(key, "")).isdigit():
                    values.add(str(inp[key]))
    return values


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