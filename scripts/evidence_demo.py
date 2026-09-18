from dotenv import load_dotenv
load_dotenv()

from datetime import datetime, timezone
from cua.surface.browser import BrowserSession
from cua.agent.llm_client import LLMClient
from cua.agent.loop import AgentLoop
from cua.artifact.recorder import record
from cua.artifact.schema import Checkpoint, OutcomeRule
from cua.artifact import store
from cua.replay.executor import replay
from cua.observability.logger import log_discovery, log_replay



import os



TEST_USERNAME_FAIL = os.environ.get("PARABANK_USERNAME_FAIL", "test_user")
TEST_PASSWORD_FAIL = os.environ.get("PARABANK_PASSWORD_FAIL", "test_password")

TEST_USERNAME_SUCCESS = os.environ.get("PARABANK_USERNAME_SUCCESS", "test_user")
TEST_PASSWORD_SUCCESS = os.environ.get("PARABANK_PASSWORD_SUCCESS", "test_password")


ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# /discovery_run = llm driven
with BrowserSession(headless=False) as session:
    discovery_dir = f"evidence/discovery_run_{ts}"
    # session = BrowserSession(headless=False)
    llm = LLMClient()
    agent = AgentLoop(session, llm, max_steps=8, evidence_dir=discovery_dir)
    result = agent.run(
        goal=(
            f"Log in with username '{TEST_USERNAME_SUCCESS}' and password '{TEST_PASSWORD_SUCCESS}'. "
            "When calling done, include exactly these output keys: "
            "'login_succeeded' (string 'true' or 'false') and 'message' (a short description)."
        ),
        start_url="https://parabank.parasoft.com/parabank/index.htm",
    )
log_discovery(result, discovery_dir, sensitive_values=[TEST_PASSWORD_SUCCESS])
print(f"[1/3] Discovery run saved to {discovery_dir}")

assert result.success, f"Discovery run failed: {result.stop_reason}"





# Record and save the capability artifact from this run
capability = record(
    run_result=result,
    capability_id="parabank.login",
    entry_url="https://parabank.parasoft.com/parabank/index.htm",
    param_map={f"{TEST_USERNAME_SUCCESS}": "username", f"{TEST_PASSWORD_SUCCESS}": "password"},
    output_keys=["login_succeeded", "message"],
    checkpoint=Checkpoint(kind="url_contains", expected="/overview.htm"),
    description="Log into ParaBank with a username and password.",
)
capability.outcome_rules.append(
    OutcomeRule(
        name="invalid_credentials", 
        kind="text_visible",
        expected="could not be verified", 
        description="Wrong username/password"
    )
)
artifact_path = store.save(capability)
print(f"Artifact saved to {artifact_path}")





# deterministic run with success
with BrowserSession(headless=False) as session:
    replay_success_dir = f"evidence/replay_run_success_{ts}"
    # session = BrowserSession(headless=False)
    success_result = replay(session, capability, {"username": f"{TEST_USERNAME_SUCCESS}", "password": f"{TEST_PASSWORD_SUCCESS}"})
log_replay(success_result, replay_success_dir, {"username": f"{TEST_USERNAME_SUCCESS}", "password": f"{TEST_PASSWORD_SUCCESS}"})
print(f"[2/3] Successful replay saved to {replay_success_dir} — status: {success_result.status.value}")





# deterministic run with business-outcome failure
with BrowserSession(headless=False) as session:
    replay_outcome_dir = f"evidence/replay_run_business_outcome_{ts}"
    # session = BrowserSession(headless=False)
    outcome_result = replay(session, capability, {"username": f"{TEST_USERNAME_FAIL}", "password": f"{TEST_PASSWORD_FAIL}"})

log_replay(outcome_result, replay_outcome_dir,{"username": f"{TEST_USERNAME_FAIL}", "password": f"{TEST_PASSWORD_FAIL}"})
print(f"[3/3] Business-outcome replay saved to {replay_outcome_dir} — status: {outcome_result.status.value}")
