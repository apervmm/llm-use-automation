import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path

from agent.loop import AgentRunResult
from replay.outcomes import ReplayResult
from safety.redaction import redact_any


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


def log_discovery(
    result: AgentRunResult, 
    evidence_dir: str, 
    sensitive_values: list[str] | None = None, 
    run_id: str | None = None
) -> Path:
    """
        Writes a structured summary of a discovery run alongside the screenshots AgentLoop already saved into evidence_dir
    """
    out_dir = Path(evidence_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "run_type": "discovery",
        "run_id": run_id,
        "timestamp": _timestamp(),
        "goal": result.goal,
        "success": result.success,
        "stop_reason": result.stop_reason,
        "escalations": result.escalations,
        "outputs": result.outputs,
        "transcript": [_to_jsonable(step) for step in result.transcript],
    }

    summary = redact_any(summary, sensitive_values=set(sensitive_values or []))

    path = out_dir / "result.json"
    path.write_text(json.dumps(summary, indent=2))
    return path


def log_replay(
    result: ReplayResult, 
    evidence_dir: str, 
    inputs: dict,
    run_id: str | None = None
) -> Path:
    """
        Writes a structured summary of a single replay invocation
    """
    out_dir = Path(evidence_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "run_type": "replay",
        "run_id": run_id,
        "timestamp": _timestamp(),
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
    accounts = {str(v) for k, v in {**inputs, **(result.outputs or {})}.items() if "account" in k.lower() and str(v).isdigit()}
    summary = redact_any(summary, sensitive_values=secrets, masked_values=accounts)

    path = out_dir / "result.json"
    path.write_text(json.dumps(summary, indent=2))
    return path