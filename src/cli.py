import json
from pathlib import Path

import click
import yaml
from dotenv import load_dotenv

load_dotenv()

from surface.browser import BrowserSession
from agent.llm_client import LLMClient
from agent.loop import AgentLoop
from artifact.recorder import record
from artifact.schema import Checkpoint, OutcomeRule
from artifact import store
from replay.executor import replay as run_replay
from replay.outcomes import ReplayStatus
from escalation.operator_cli import to_operator
from observability.logger import log_discovery, log_replay


import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


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
    config = yaml.safe_load(Path(config_path).read_text())
    capability_id = config["capability_id"]
    evidence_dir = f"evidence/discovery_{capability_id}"

    with BrowserSession(headless=False) as session:
        _authenticate_if_needed(session, config)

        agent = AgentLoop(
            session, 
            LLMClient(), 
            max_steps=max_steps,
            evidence_dir=evidence_dir, 
            on_escalation=to_operator
        )
        result = agent.run(goal=config["goal"], start_url=config["url"])

    log_discovery(result, evidence_dir)
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
        checkpoint=Checkpoint(**config["checkpoint"]),
        description=f"Recorded from goal: {config['goal']}",
    )
    capability.outcome_rules.extend(OutcomeRule(**r) for r in config.get("outcome_rules", []))

    saved_path = store.save(capability)
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
    config = yaml.safe_load(Path(config_path).read_text())
    capability_id = config["capability_id"]
    capability = store.load(capability_id, version=version_)
    input_dict = _parse_pairs(inputs)
    evidence_dir = f"evidence/replay_{capability_id}"

    with BrowserSession(headless=False) as session:
        _authenticate_if_needed(session, config)
        result = run_replay(session, capability, input_dict, confirmed=confirmed, on_escalation=to_operator)

    log_replay(result, evidence_dir, input_dict)
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