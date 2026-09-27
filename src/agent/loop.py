from pathlib import Path

from surface.browser import BrowserSession
from surface.types import PageState
from escalation.handoff import (
    raise_escalation,
    EscalationReason,
    OperatorDecision,
)

from .llm_client import LLMClient
from .prompts import SYSTEM_PROMPT, TOOLS
from .types import AgentRunResult, TranscriptStep
from .run import DiscoveryRun
from .helpers import execute_tool, first_tool_use, observation_text, take_snapshot, tool_result_turn, user_turn


__all__ = ["AgentLoop", "AgentRunResult", "TranscriptStep"]


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
            max_escalations: int = 2,
            run_id: str | None = None,
        ):
        self.session = session
        self.llm = llm
        self.max_steps = max_steps
        self.evidence_dir = evidence_dir
        self.on_escalation = on_escalation
        self.max_escalations = max_escalations
        self.run_id = run_id
        Path(evidence_dir).mkdir(parents=True, exist_ok=True)


    def run(self, goal: str, start_url: str) -> AgentRunResult:
        nav = self.session.goto(start_url)
        if not nav.success:
            return AgentRunResult(goal, False, f"entry_unreachable: {nav.error}")
        run = DiscoveryRun(goal=goal, step_limit=self.max_steps, state=self._snapshot("step_0"))
        run.messages.append(user_turn(observation_text(goal, run.state)))
        step_num = 1
        while True:
            if step_num > run.step_limit:
                if final := self._on_step_limit(run, step_num):
                    return final
                continue
            response = self.llm.decide(run.messages, SYSTEM_PROMPT, TOOLS)
            tool_use = first_tool_use(response)
            if tool_use is None:
                if final := self._on_no_tool_call(run, step_num):
                    return final
                continue
            run.messages.append({"role": "assistant", "content": response.content})
            if tool_use.name == "done":
                return self._finish(run, step_num, tool_use)
            if final := self._act(run, step_num, tool_use):
                return final
            step_num += 1


    def _act(self, run: DiscoveryRun, step_num: int, tool_use) -> AgentRunResult | None:
        result_text, run.state, ref, success = execute_tool(
            self.session, tool_use, run.state, step_num, self.evidence_dir)
        run.consecutive_failures = 0 if success else run.consecutive_failures + 1
        run.transcript.append(TranscriptStep(
            step_num, run.state.url, tool_use.name, tool_use.input, success, result_text,
            screenshot_path=f"{self.evidence_dir}/step_{step_num}.png",
            resolved_ref=ref,
        ))
        stuck = not success and run.consecutive_failures >= self.STUCK_FAILURE_THRESHOLD
        if stuck and self._can_escalate(run):
            decision = self._escalate(
                run, step_num, f"{run.consecutive_failures} consecutive failed actions — agent appears stuck.")
            if decision == OperatorDecision.ABORT:
                return run.result(False, "aborted_by_operator")
            run.consecutive_failures = 0
            run.state = self._snapshot(f"step_{step_num}_resumed")
            run.messages.append(tool_result_turn(tool_use.id, result_text))
            run.messages.append(user_turn(observation_text(None, run.state, include_goal=False)))
            return None
        run.messages.append(tool_result_turn(tool_use.id, result_text))
        return None
    

    def _finish(self, run: DiscoveryRun, step_num: int, tool_use) -> AgentRunResult:
        run.outputs = tool_use.input.get("outputs", {})
        run.transcript.append(TranscriptStep(step_num, run.state.url, "done", tool_use.input, True, "goal completed"))
        return run.result(True, "goal_met")


    def _on_step_limit(self, run: DiscoveryRun, step_num: int) -> AgentRunResult | None:
        if self._can_escalate(run):
            decision = self._escalate(run, step_num, f"Reached max_steps ({run.step_limit}) without completing the goal.")
            if decision == OperatorDecision.ABORT:
                return run.result(False, "aborted_by_operator")
            if decision == OperatorDecision.RESUME:
                run.step_limit += self.STUCK_STEP_EXTENSION
                self._observe_again(run, step_num)
                return None
        return run.result(False, "max_steps_exceeded")
    

    def _on_no_tool_call(self, run: DiscoveryRun, step_num: int) -> AgentRunResult | None:
        if self._can_escalate(run):
            decision = self._escalate(run, step_num, "Model did not return a tool call — no clear next action.")
            if decision == OperatorDecision.ABORT:
                return run.result(False, "aborted_by_operator")
            if decision == OperatorDecision.RESUME:
                self._observe_again(run, step_num)
                return None
        return run.result(False, "no_tool_call")


    def _can_escalate(self, run: DiscoveryRun) -> bool:
        return bool(self.on_escalation) and len(run.escalations) < self.max_escalations
    

    def _escalate(self, run: DiscoveryRun, step_num: int, detail: str) -> OperatorDecision:
        request = raise_escalation(
            self.session,
            run.handoff_state, 
            EscalationReason.DISCOVERY_STUCK, 
            run.goal,
            detail,
            current_step=step_num, 
            evidence_dir=self.evidence_dir, 
            run_id=self.run_id,
        )
        decision, record = self.on_escalation(request, run.handoff_state)
        run.escalations.append(record)
        return decision
            

    def _observe_again(self, run: DiscoveryRun, step_num: int) -> None:
        run.state = self._snapshot(f"step_{step_num}_resumed")
        run.messages.append(user_turn(observation_text(run.goal, run.state)))


    def _snapshot(self, name: str) -> PageState:
        return take_snapshot(self.session, self.evidence_dir, name)
    