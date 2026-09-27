import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path

from agent.loop import AgentRunResult


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def to_jsonable(obj):
    """Recursively turn dataclasses and enums into plain JSON-serializable data"""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: to_jsonable(v) for k, v in asdict(obj).items()}
    if hasattr(obj, "value") and hasattr(obj, "name") and not isinstance(obj, (str, int)):
        return obj.value  # Enum
    if isinstance(obj, list):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    return obj


def account_values(fields: dict) -> set[str]:
    return {str(v) for k, v in fields.items() if "account" in k.lower() and str(v).isdigit()}


def discovery_account_values(result: AgentRunResult) -> set[str]:
    values = account_values(result.outputs or {})
    for step in result.transcript:
        inp = step.tool_input or {}
        if "account" in str(inp.get("element_name", "")).lower():
            for key in ("option_value", "text"):
                if str(inp.get(key, "")).isdigit():
                    values.add(str(inp[key]))
    return values


def write_summary(evidence_dir: str, summary: dict) -> Path:
    out_dir = Path(evidence_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "result.json"
    path.write_text(json.dumps(summary, indent=2))
    return path