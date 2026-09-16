from .handoff import EscalationRequest, HandoffState, OperatorDecision

import json
import uuid
from pathlib import Path


def to_operator(request: EscalationRequest, state: HandoffState, evidence_dir: str = "evidence/escalations") -> OperatorDecision:
    print(f"Reason: {request.reason.value}")
    print(f"Task: {request.capability_or_goal}")
    print(f"Step:  {request.current_step}")
    print(f"Current URL: {request.current_url}")
    print(f"Detail: {request.detail}")

 
    action_note = input(
        "Describe what you did"
        "[type `abort` = stops the run or `enter` = to submit a note or skip]: "
    )

    decision = OperatorDecision.ABORT if action_note.strip().lower() == "abort" else OperatorDecision.RESUME

    if decision == OperatorDecision.RESUME:
        if action_note.strip():
            state.record_human_action(action_note.strip())
        state.resume_automation()
        print("Resuming...\n")
    else:
        print("Aborting run at operator's request...\n")


    Path(evidence_dir).mkdir(parents=True, exist_ok=True)
    record_path = Path(evidence_dir) / f"escalation_{uuid.uuid4().hex}.json"
    record_path.write_text(json.dumps({
        "reason": request.reason.value,
        "capability_or_goal": request.capability_or_goal,
        "current_step": request.current_step,
        "current_url": request.current_url,
        "detail": request.detail,
        "screenshot_path": request.screenshot_path,
        "timestamp": request.timestamp,
        "operator_decision": decision.value,
        "human_actions": state.human_actions_log,
    }, indent=2))
    print(f"Escalation record saved to {record_path}")


    return decision