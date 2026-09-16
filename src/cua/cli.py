import json
import click
from dotenv import load_dotenv

load_dotenv()

from cua.surface.browser import BrowserSession
from cua.agent.llm_client import LLMClient
from cua.agent.loop import AgentLoop
from cua.artifact.recorder import record
from cua.artifact.schema import Checkpoint
from cua.artifact import store
from cua.replay.executor import replay as run_replay
from cua.escalation.operator_cli import to_operator
from cua.observability.logger import log_discovery, log_replay

PARABANK_URL = "https://parabank.parasoft.com/parabank/index.htm"


def _parse_pairs(text: str) -> dict:
    """
        'a=1,b=2' -> {'a': '1', 'b': '2'}
    """
    return dict(pair.split("=", 1) for pair in text.split(",") if pair)


@click.group()
def cli():
    """ParaBank Automation System"""


@cli.command()
@click.option("--goal", required=True, help="Natural-language goal for the agent.")
@click.option("--capability-id", required=True, help="Name to save the resulting capability as.")
@click.option("--params", required=True, help="Comma-separated literal=paramname, e.g. john=username,demo=password")
@click.option("--outputs", required=True, help="Comma-separated output keys, e.g. login_succeeded,message")
@click.option("--checkpoint", required=True, help="URL substring that indicates success, e.g. /overview.htm")
@click.option("--url", default=PARABANK_URL, show_default=True)
def discover(goal, capability_id, params, outputs, checkpoint, url):
    """Run a live, LLM-driven discovery session and save the resulting capability."""
    evidence_dir = f"evidence/discovery_run_{capability_id}"

    with BrowserSession(headless=False) as session:
        agent = AgentLoop(session, LLMClient(), evidence_dir=evidence_dir)
        result = agent.run(goal=goal, start_url=url)

    log_discovery(result, evidence_dir)
    click.echo(f"Discovery {'succeeded' if result.success else 'failed'} ({result.stop_reason})")
    if not result.success:
        raise SystemExit(1)

    capability = record(
        run_result=result,
        capability_id=capability_id,
        entry_url=url,
        param_map=_parse_pairs(params),
        output_keys=outputs.split(","),
        checkpoint=Checkpoint(kind="url_contains", expected=checkpoint),
        description=f"Recorded from goal: {goal}",
    )
    click.echo(f"Capability saved to {store.save(capability)}")


@cli.command()
@click.option("--capability-id", required=True, help="Capability to replay.")
@click.option("--inputs", required=True, help="Comma-separated key=value, e.g. username=john,password=demo")
def replay(capability_id, inputs):
    """Deterministically replay a saved capability — no LLM involved."""
    capability = store.load(capability_id)
    input_dict = _parse_pairs(inputs)
    evidence_dir = f"evidence/replay_run_{capability_id}"

    with BrowserSession(headless=False) as session:
        result = run_replay(session, capability, input_dict, on_escalation=to_operator)

    log_replay(result, evidence_dir, input_dict)
    click.echo(f"Status: {result.status.value}")
    click.echo(json.dumps({
        "outputs": result.outputs,
        "outcome_name": result.outcome_name,
        "error": result.error,
    }, indent=2))


if __name__ == "__main__":
    cli()