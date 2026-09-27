import click

from agent.llm_client import LLMClient
from agent.loop import AgentLoop
from artifact import store
from artifact.recorder import record
from artifact.schema import Checkpoint, OutcomeRule
from escalation.operator_cli import to_operator
from observability.logger import log_discovery
from replay.checkpoint import checkpoint_met
from surface.browser import BrowserSession
from .utils import authenticate_if_needed, build_param_map, copy_to_evidence, load_config, new_evidence_dir, secret_literals


@click.command()
@click.option("--config", "config_path", required=True, type=click.Path(exists=True), help="Path to a capability YAML file")
@click.option("--max-steps", default=15, show_default=True)
def discover(config_path, max_steps):
    """
        LLM-driven discovery session using a capability config file
    """
    config = load_config(config_path)
    capability_id = config["capability_id"]
    run_id, evidence_dir = new_evidence_dir("discovery", capability_id)

    with BrowserSession(headless=False) as session:
        authenticate_if_needed(session, config)
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
        
    log_discovery(result, evidence_dir, sensitive_values=secret_literals(config), run_id=run_id)
    click.echo(f"Discovery {'succeeded' if result.success else 'failed'} ({result.stop_reason})")
    if not result.success:
        raise SystemExit(1)

    capability = record(
        run_result=result,
        capability_id=capability_id,
        entry_url=config["url"],
        param_map=build_param_map(config, result.transcript),
        output_keys=config.get("outputs", []),
        checkpoint=checkpoint,
        description=f"Recorded from goal: {config['goal']}",
        outcome_derived_outputs=config.get("outcome_derived_outputs", []), 
    )
    capability.outcome_rules.extend(OutcomeRule(**r) for r in config.get("outcome_rules", []))
    saved_path = store.save(capability)
    copy_to_evidence(saved_path, evidence_dir)
    click.echo(f"Capability saved to {saved_path} (version={capability.version}, risk_level={capability.risk_level.value})")
