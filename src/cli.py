import json
from pathlib import Path

import click
import yaml
from dotenv import load_dotenv
from datetime import datetime, timezone
import uuid
import shutil

load_dotenv()

from surface.browser import BrowserSession
from agent.llm_client import LLMClient
from agent.loop import AgentLoop
from artifact.recorder import record
from artifact.schema import Checkpoint, OutcomeRule
from artifact import store
from replay.executor import replay as run_replay
from replay.outcomes import ReplayStatus
from replay.checkpoint import checkpoint_met
from escalation.operator_cli import to_operator
from observability.logger import log_discovery, log_replay

from replay.executor import input_errors


import sys
import os
# sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))



def _load_config(path: str) -> dict:
    # text = Path(path).read_text()
    # config = yaml.safe_load(Path(path).read_text())
    def expand(value):
        if isinstance(value, str):
            return os.path.expandvars(value)
        if isinstance(value, dict):
            return {expand(key): expand(item) for key, item in value.items()}
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value

    return expand(yaml.safe_load(Path(path).read_text()))

    # text = os.path.expandvars(text)  
    # return yaml.safe_load(text)
    # return _expand_env(config)


def _parse_pairs(text: str) -> dict:
    return dict(pair.split("=", 1) for pair in text.split(",") if pair)


def _find_select_option_value(transcript) -> str | None:
    for t in transcript:
        if t.tool_name == "select_option" and t.success:
            return t.tool_input.get("option_value")
    return None


def _authenticate_if_needed(session: BrowserSession, config: dict):
    auth_id = config.get("auth_capability_id")
    if not auth_id:
        return
    auth_capability = store.load(auth_id)
    auth_inputs = config.get("auth_inputs", {})
    result = run_replay(session, auth_capability, auth_inputs)
    if result.status != ReplayStatus.SUCCESS:
        raise SystemExit(f"Auth via '{auth_id}' failed (status={result.status.value}): {result.error}")
    click.echo(f"Authenticated via '{auth_id}'.")


@click.group()
def cli():
    """Computer-use automation CLI"""


@cli.command()
@click.option(
    "--config", 
    "config_path", 
    required=True, 
    type=click.Path(exists=True),
    help="Path to a capability YAML file (see capabilities/*.yaml for examples).")
@click.option(
    "--max-steps",
    default=15, 
    show_default=True)
def discover(config_path, max_steps):
    """
    LLM-driven discovery session using a capability config file
    To reuse an existing capability, use `replay`.
    """
    config = _load_config(config_path)
    capability_id = config["capability_id"]

    run_id = uuid.uuid4().hex[:12]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    evidence_dir = f"evidence/discovery_{capability_id}_{ts}_{run_id}"

    with BrowserSession(headless=False) as session:
        _authenticate_if_needed(session, config)

        checkpoint = Checkpoint(**config["checkpoint"]) 

        agent = AgentLoop(
            session, 
            LLMClient(), 
            max_steps=max_steps,
            evidence_dir=evidence_dir, 
            on_escalation=to_operator,
            run_id=run_id
        )
        result = agent.run(goal=config["goal"], start_url=config["url"])

        if result.success and not checkpoint_met(session, checkpoint):
            result.success = False
            result.stop_reason = "checkpoint_not_met_despite_done"
        
    sensitive = [lit for lit, name in config.get("params", {}).items() if name.lower() in ("password", "pin", "ssn")]
    log_discovery(result, evidence_dir, sensitive_values=sensitive, run_id=run_id)
    click.echo(f"Discovery {'succeeded' if result.success else 'failed'} ({result.stop_reason})")


    if not result.success:
        raise SystemExit(1)

    param_map = dict(config.get("params", {}))
    if config.get("select_param"):
        chosen = _find_select_option_value(result.transcript)
        if chosen is None:
            raise SystemExit("Config has select_param but no successful select_option step was found.")
        param_map[chosen] = config["select_param"]
        click.echo(f"Agent selected '{chosen}' -> parameterized as '{config['select_param']}'.")

    capability = record(
        run_result=result,
        capability_id=capability_id,
        entry_url=config["url"],
        param_map=param_map,
        output_keys=config.get("outputs", []),
        # checkpoint=Checkpoint(**config["checkpoint"]),
        checkpoint=checkpoint,
        description=f"Recorded from goal: {config['goal']}",
        outcome_derived_outputs=config.get("outcome_derived_outputs", []), 
    )
    capability.outcome_rules.extend(OutcomeRule(**r) for r in config.get("outcome_rules", []))

    saved_path = store.save(capability)

    evidence_artifacts = Path(evidence_dir).parent / "artifacts"
    evidence_artifacts.mkdir(parents=True, exist_ok=True)
    shutil.copy(saved_path, evidence_artifacts / saved_path.name)
    
    click.echo(f"Capability saved to {saved_path} (version={capability.version}, risk_level={capability.risk_level.value})")


@cli.command()
@click.option(
    "--config", 
    "config_path", 
    required=True, 
    type=click.Path(exists=True),
    help="Path to the same capability YAML file used for discovery.")
@click.option(
    "--inputs", 
    default="", 
    help="Comma-separated key=value, e.g. amount=1000,down_payment=10")
@click.option(
    "--version", 
    "version_", 
    type=int, 
    default=None, 
    help="Pin a specific saved version.")
@click.option(
    "--confirmed", 
    is_flag=True, 
    default=False, 
    help="Skip the risky-confirmation prompt.")
def replay(config_path, inputs, version_, confirmed):
    """
    Deterministic replay of a saved capability
    """
    config = _load_config(config_path)
    capability_id = config["capability_id"]
    capability = store.load(capability_id, version=version_)
    input_dict = _parse_pairs(inputs)

    if errors := input_errors(capability, input_dict):
        raise SystemExit("Invalid inputs: " + "; ".join(errors))
    
    run_id = uuid.uuid4().hex[:12]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    evidence_dir = f"evidence/replay_{capability_id}_{ts}_{run_id}"

    

    with BrowserSession(headless=False) as session:
        _authenticate_if_needed(session, config)
        result = run_replay(
            session, 
            capability, 
            input_dict, 
            confirmed=confirmed, 
            on_escalation=to_operator,
            run_id=run_id, 
            evidence_dir=evidence_dir
        )

    log_replay(result, evidence_dir, input_dict, run_id=run_id)
    click.echo(f"Status: {result.status.value}")
    click.echo(json.dumps({
        "outputs": result.outputs,
        "outcome_name": result.outcome_name,
        "error": result.error,
    }, indent=2))

    if result.status == ReplayStatus.FAILURE:
        raise SystemExit(1)


if __name__ == "__main__":
    cli()