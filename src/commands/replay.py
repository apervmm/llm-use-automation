import click

from artifact import store
from escalation.operator_cli import to_operator
from observability.logger import log_replay
from replay.executor import input_errors, replay as run_replay
from replay.outcomes import ReplayStatus
from surface.browser import BrowserSession
from .utils import authenticate_if_needed, load_config, new_evidence_dir, parse_pairs, print_replay_result


@click.command()
@click.option("--config", "config_path", required=True, type=click.Path(exists=True), help="Path to the same capability YAML file used for discovery.")
@click.option("--inputs", default="", help="Comma-separated key=value, e.g. amount=1000,down_payment=10")
@click.option("--version", "version_", type=int, default=None, help="Pin a specific saved version.")
@click.option("--confirmed", is_flag=True, default=False, help="Skip the risky-confirmation prompt.")
def replay(config_path, inputs, version_, confirmed):
    """Replay a saved capability deterministically"""
    config = load_config(config_path)
    capability_id = config["capability_id"]
    capability = store.load(capability_id, version=version_)
    input_dict = parse_pairs(inputs)
    if errors := input_errors(capability, input_dict):
        raise SystemExit("Invalid inputs: " + "; ".join(errors))

    run_id, evidence_dir = new_evidence_dir("replay", capability_id)
    with BrowserSession(headless=False) as session:
        authenticate_if_needed(session, config)
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
    print_replay_result(result)
    if result.status == ReplayStatus.FAILURE:
        raise SystemExit(1)