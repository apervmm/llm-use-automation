from dataclasses import dataclass, field
from pathlib import Path

from surface.browser import BrowserSession
from surface.perception import snapshot
from surface.types import PageState, ElementRef

from .llm_client import LLMClient
from .prompts import SYSTEM_PROMPT, TOOLS


from escalation.handoff import (
    raise_escalation,
    EscalationReason,
    HandoffState,
    OperatorDecision,
)


@dataclass
class TranscriptStep:
    step_num: int
    page_url: str
    tool_name: str
    tool_input: dict
    success: bool
    detail: str
    screenshot_path: str | None = None
    resolved_ref: ElementRef | None = None 


@dataclass
class AgentRunResult:
    goal: str
    success: bool
    stop_reason: str
    transcript: list[TranscriptStep] = field(default_factory=list)
    outputs: dict = field(default_factory=dict)
    escalations: int = 0


class AgentLoop:

    STUCK_FAILURE_THRESHOLD = 3 # Limit on consecutive failures before escalation

    STUCK_STEP_EXTENSION = 3 # Number of additional steps to allow after an escalation before giving up

    def __init__(
            self, 
            session: BrowserSession, 
            llm: LLMClient, 
            max_steps: int = 15, 
            evidence_dir: str = "evidence/discovery",
            on_escalation=None, 
            max_escalations: int = 2
        ):
        self.session = session
        self.llm = llm
        self.max_steps = max_steps
        self.evidence_dir = evidence_dir
        self.on_escalation = on_escalation
        self.max_escalations = max_escalations
        Path(evidence_dir).mkdir(parents=True, exist_ok=True)


    def run(self, goal: str, start_url: str) -> AgentRunResult:
        self.session.goto(start_url)
        transcript: list[TranscriptStep] = []
        outputs: dict = {}

        state = snapshot(self.session, screenshot_path=f"{self.evidence_dir}/step_0.png")
        messages = [{"role": "user", "content": self._observation_text(goal, state)}]

        handoff_state = HandoffState()
        escalations_used = 0
        consecutive_failures = 0
        step_limit = self.max_steps



        # for step_num in range(1, self.max_steps + 1):
        step_num = 1
        while True:
            if step_num > step_limit:
                if self.on_escalation and escalations_used < self.max_escalations:
                    decision = self._escalate(
                        handoff_state, goal, step_num,
                        f"Reached max_steps ({step_limit}) without completing the goal.",
                    )
                    escalations_used += 1
                    if decision == OperatorDecision.ABORT:
                        return AgentRunResult(goal, False, "aborted_by_operator",transcript, outputs, escalations_used)
                    if decision == OperatorDecision.RESUME:
                        step_limit += self.STUCK_STEP_EXTENSION
                        state = snapshot(self.session, screenshot_path=f"{self.evidence_dir}/step_{step_num}_resumed.png")
                        messages.append({"role": "user", "content": self._observation_text(goal, state)})
                        continue
                return AgentRunResult(goal, False, "max_steps_exceeded", transcript, outputs, escalations_used)

            response = self.llm.decide(messages, SYSTEM_PROMPT, TOOLS)
            tool_use = next((b for b in response.content if b.type == "tool_use"), None)

            if tool_use is None:
                if self.on_escalation and escalations_used < self.max_escalations:
                    decision = self._escalate(
                        handoff_state, goal, step_num,
                        "Model did not return a tool call — no clear next action.",
                    )

                    escalations_used += 1
                    if decision == OperatorDecision.ABORT:
                        return AgentRunResult(goal, False, "aborted_by_operator",transcript, outputs, escalations_used)
                    if decision == OperatorDecision.RESUME:
                        state = snapshot(self.session, screenshot_path=f"{self.evidence_dir}/step_{step_num}_resumed.png")
                        messages.append({"role": "user", "content": self._observation_text(goal, state)})
                        continue
                return AgentRunResult(goal, False, "no_tool_call", transcript, outputs, escalations_used)

            messages.append({"role": "assistant", "content": response.content})

            if tool_use.name == "done":
                outputs = tool_use.input.get("outputs", {})
                transcript.append(TranscriptStep(
                    step_num, state.url, "done", tool_use.input, True, "goal completed"))
                return AgentRunResult(goal, True, "goal_met", transcript, outputs, escalations_used)

            result_text, state, ref= self._execute(tool_use, state, step_num)
            success = "ERROR" not in result_text
            consecutive_failures = 0 if success else consecutive_failures + 1


            transcript.append(TranscriptStep(
                step_num, 
                state.url, 
                tool_use.name, 
                tool_use.input, 
                success, 
                result_text,
                screenshot_path=f"{self.evidence_dir}/step_{step_num}.png",
                resolved_ref=ref
            ))

            if (not success and consecutive_failures >= self.STUCK_FAILURE_THRESHOLD
                    and self.on_escalation and escalations_used < self.max_escalations):
                decision = self._escalate(
                    handoff_state, goal, step_num,
                    f"{consecutive_failures} consecutive failed actions — agent appears stuck.",
                )
                escalations_used += 1
                if decision == OperatorDecision.ABORT:
                    return AgentRunResult(goal, False, "aborted_by_operator", transcript, outputs, escalations_used)
                consecutive_failures = 0
                state = snapshot(self.session, screenshot_path=f"{self.evidence_dir}/step_{step_num}_resumed.png")
                messages.append({
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": tool_use.id, "content": result_text}],
                })
                messages.append({"role": "user", "content": self._observation_text(None, state, include_goal=False)})
                step_num += 1
                continue

            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_text,
                }],
            })

            step_num += 1


    def _escalate(self, handoff_state: HandoffState, goal: str, step_num: int, detail: str) -> OperatorDecision:
        req = raise_escalation(
            self.session,
            handoff_state,
            EscalationReason.DISCOVERY_STUCK,
            goal,
            detail,
            current_step=step_num,
        )
        return self.on_escalation(req, handoff_state)
            
    def _execute(
        self, 
        tool_use, 
        state: PageState, 
        step_num: int
    ) -> tuple[str, PageState, ElementRef | None]:
        
        name, inp = tool_use.name, tool_use.input

        if name == "click":
            ref = state.find_ref(inp["element_name"], inp.get("role"))
            if ref is None:
                return f"ERROR: no element named '{inp['element_name']}' found on this page.",  state, None
            result = self.session.click(ref, description=inp["element_name"])
        elif name == "type_text":
            ref = state.find_ref(inp["element_name"], "textbox")
            if ref is None:
                return f"ERROR: no textbox named '{inp['element_name']}' found on this page.",  state, None
            result = self.session.type_text(ref, inp["text"], description=inp["element_name"])
        elif name == "navigate":
            ref = None
            result = self.session.goto(inp["url"])
        elif name == "select_option":
            ref = state.find_ref(inp["element_name"], "combobox")
            if ref is None:
                return f"ERROR: no dropdown named '{inp['element_name']}' found on this page.", state, None
            result = self.session.select_option(ref, inp["option_value"], description=inp["element_name"])
        elif name == "read":
            ref = None
            element_name = inp.get("element_name")
            if element_name:
                ref = state.find_ref(element_name)
            return f"Recorded {inp['label']} = {inp['value']}.", state, ref
        else:
            return f"ERROR: unknown tool '{name}'.", state, None
        

        if not result.success:
            return f"ERROR: {name} failed — {result.error}", new_state, ref

        self.session.page.wait_for_timeout(500)

        new_state = snapshot(self.session, screenshot_path=f"{self.evidence_dir}/step_{step_num}.png")
        
        return f"{name} succeeded. New page: {self._observation_text(None, new_state, include_goal=False)}", new_state, ref


    def _observation_text(self, goal: str | None, state: PageState, include_goal: bool = True) -> str:
        lines = []
        for el in state.interactive_elements:
            line = f"- [{el.role}] '{el.accessible_name}'"
            if el.options:
                line += f" (options: {', '.join(el.options)})"
            lines.append(line)
        elements = "\n".join(lines)

        parts = []
        if include_goal and goal:
            parts.append(f"GOAL: {goal}\n")
        parts.append(f"Current URL: {state.url}\nPage title: {state.title}")
        parts.append(f"Interactive elements:\n{elements}")
        parts.append(f"Visible text (truncated): {state.visible_text_summary[:500]}")
        return "\n\n".join(parts)