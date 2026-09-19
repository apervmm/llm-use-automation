from surface.browser import BrowserSession
from artifact import store
from artifact.schema import OutcomeRule
from replay.executor import replay

capability = store.load("parabank.login")

# Add an outcome rule for wrong credentials (edit + re-save once, or add
# directly to the recorder's checkpoint args next time you record).
capability.outcome_rules.append(
    OutcomeRule(name="invalid_credentials", kind="text_visible",
                expected="could not be verified", description="Wrong username/password")
)

print("=== Replay with correct-shaped but WRONG credentials ===")
session = BrowserSession(headless=False)
result = replay(session, capability, {"username": "asd", "password": "asd"})
print(result)
session.close()

print("\n=== Replay with VALID credentials (use your real ParaBank test account) ===")
session = BrowserSession(headless=False)
result = replay(session, capability, {"username": "john", "password": "demo"})  # replace with real creds
print(result)
session.close()