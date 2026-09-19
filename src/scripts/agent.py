from dotenv import load_dotenv
load_dotenv()

from surface.browser import BrowserSession
from agent.llm_client import LLMClient
from agent.loop import AgentLoop

session = BrowserSession(headless=False)
llm = LLMClient()
agent = AgentLoop(session, llm, max_steps=10)

result = agent.run(
    goal="Log in with username 'john' and password 'demo', then report whether login succeeded.",
    start_url="https://parabank.parasoft.com/parabank/index.htm",
)

print("Success:", result.success)
print("Stop reason:", result.stop_reason)
print("Outputs:", result.outputs)
for i, step in enumerate(result.transcript):
    print(f"{i} step: {step.step_num}: {step.tool_name}({step.tool_input}) -> {step.success}")
    print(f"    {step.detail}")

session.close()