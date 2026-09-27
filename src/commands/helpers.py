import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml

from artifact import store
from replay.executor import replay as run_replay
from replay.outcomes import ReplayResult, ReplayStatus
from safety.redaction import is_secret_name
from surface.browser import BrowserSession


# ------------ Configs and inputs ------------
def load_config(path: str) -> dict:
    return _expand_env(yaml.safe_load(Path(path).read_text()))


def _expand_env(value):
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, dict):
        return {_expand_env(key): _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    return value


def parse_pairs(text: str) -> dict:
    """
        amount=1000,down_payment=10 -> {'amount': '1000', 'down_payment': '10'}
    """
    result = {}
    for pair in filter(None, text.split(",")):
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise click.BadParameter(f"Expected key=value, got '{pair}'", param_hint="--inputs")
        result[key.strip()] = value
    return result
    #return dict(pair.split("=", 1) for pair in text.split(",") if pair)


def new_evidence_dir(kind: str, capability_id: str) -> tuple[str, str]:
    run_id = uuid.uuid4().hex[:12]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return run_id, f"evidence/{kind}_{capability_id}_{ts}_{run_id}"


# ------------ Before a run ------------
def authenticate_if_needed(session: BrowserSession, config: dict) -> None:
    auth_id = config.get("auth_capability_id")
    if not auth_id:
        return
    auth_capability = store.load(auth_id)
    auth_inputs = config.get("auth_inputs", {})
    result = run_replay(session, auth_capability, auth_inputs)
    if result.status != ReplayStatus.SUCCESS:
        raise SystemExit(f"Auth via '{auth_id}' failed (status={result.status.value}): {result.error}")
    click.echo(f"Authenticated via '{auth_id}'.")


# ------------ After a discovery ------------
def secret_literals(config: dict) -> list[str]:
    return [literal for literal, name in config.get("params", {}).items() if is_secret_name(name)]


def find_select_option_value(transcript) -> str | None:
    for t in transcript:
        if t.tool_name == "select_option" and t.success:
            return t.tool_input.get("option_value")
    return None


def build_param_map(config: dict, transcript) -> dict[str, str]:
    param_map = dict(config.get("params", {}))
    if config.get("select_param"):
        chosen = find_select_option_value(transcript)
        if chosen is None:
            raise SystemExit("Config has select_param but no successful select_option step was found.")
        param_map[chosen] = config["select_param"]
        click.echo(f"Agent selected '{chosen}' -> parameterized as '{config['select_param']}'.")
    return param_map


def copy_to_evidence(saved_path: Path, evidence_dir: str) -> None:
    target = Path(evidence_dir).parent / "artifacts"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy(saved_path, target / saved_path.name)


# ------------ After a replay ------------
def print_replay_result(result: ReplayResult) -> None:
    click.echo(f"Status: {result.status.value}")
    click.echo(json.dumps({
        "outputs": result.outputs,
        "outcome_name": result.outcome_name,
        "error": result.error,
    }, indent=2))