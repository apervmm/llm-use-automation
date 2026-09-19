import os
from anthropic import Anthropic

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")


class LLMClient:

    def __init__(self):
        self.client = Anthropic()  #

    def decide(self, messages: list[dict], system_prompt: str, tools: list[dict]):
        return self.client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
            tools=tools,
        )