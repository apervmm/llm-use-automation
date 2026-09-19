from dotenv import load_dotenv
load_dotenv()

from surface.browser import BrowserSession
from agent.llm_client import LLMClient
from agent.loop import AgentLoop
from artifact.recorder import record
from artifact.schema import Checkpoint
from artifact import store

session = BrowserSession(headless=False)
llm = LLMClient()
agent = AgentLoop(session, llm, max_steps=8)

# Step 1: run live discovery (same as Module 3) — produces an AgentRunResult
result = agent.run(
    goal="Log in with username 'john' and password 'demo', then report whether login succeeded.",
    start_url="https://parabank.parasoft.com/parabank/index.htm",
)
session.close()

assert result.success, f"Discovery run failed: {result.stop_reason}"

# Step 2: feed that result into the recorder — turns literals into params,
# filters to only the successful action steps, applies explicit output keys
capability = record(
    run_result=result,
    capability_id="parabank.login",
    entry_url="https://parabank.parasoft.com/parabank/index.htm",
    param_map={"john": "username", "demo": "password"},
    output_keys=["login_succeeded", "message"],
    checkpoint=Checkpoint(kind="url_contains", expected="/overview.htm"),
    description="Log into ParaBank with a username and password.",
)

path = store.save(capability)
print("Recorded capability saved to:", path)
print(capability.model_dump_json(indent=2))