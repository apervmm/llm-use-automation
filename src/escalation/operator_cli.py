from .handoff import EscalationRequest, HandoffState, OperatorDecision, EscalationReason

import json
import uuid
from pathlib import Path



# _GUIDANCE = {
#     EscalationReason.RISKY_CONFIRMATION: (
#         "Nothing has happened yet for this step. You're deciding whether to let it run for real, "
#         "using the parameters shown above.\n"
#         "  resume -> submit it for real, right now.\n"
#         "  abort  -> do not submit anything, stop here."
#     ),
#     EscalationReason.REPLAY_FAILURE: (
#         "The step above just failed against the real page. Check the browser window (it should "
#         "now be in front):\n"
#         "  resume -> retry this step once. Use this if the page just looked slow/half-loaded.\n"
#         "  abort  -> stop here. Use this if the page shows an error, a login screen, or anything "
#         "unexpected — retrying won't fix a page that's in the wrong state."
#     ),
#     EscalationReason.DISCOVERY_STUCK: (
#         "The AI has been unable to make progress (repeated failures, or it ran out of steps). "
#         "Check the browser window:\n"
#         "  resume -> give it a bit more room to keep trying.\n"
#         "  abort  -> stop the run here."
#     ),
# }


def to_operator(request: EscalationRequest, state: HandoffState) -> OperatorDecision:
    print(f"Reason: {request.reason.value}")
    print(f"Task: {request.capability_or_goal}")
    print(f"Step:  {request.current_step}")
    print(f"Current URL: {request.current_url}")
    print(f"Detail: {request.detail}")


    while True:
        raw = input("Type 'resume' or 'abort': ").strip().lower()
        if raw == "resume":
            decision = OperatorDecision.RESUME
            break
        if raw == "abort":
            decision = OperatorDecision.ABORT
            break
        print("Please type exactly 'resume' or 'abort' — try again.")

    human_actions = []
    if decision == OperatorDecision.RESUME:
        print("Resuming...\n")
        note = input("Optional note for the record (press Enter to skip): ").strip()
        if note:
            # state.record_human_action(note)
            human_actions.append(note)
        state.resume_automation()
    else:
        print("Aborting run at operator's request...\n")


    escalation_record = {
        "reason": request.reason.value,
        "capability_or_goal": request.capability_or_goal,
        "current_step": request.current_step,
        "current_url": request.current_url,
        "detail": request.detail,
        "screenshot_path": request.screenshot_path,
        "timestamp": request.timestamp,
        "operator_decision": decision.value,
        "human_actions": human_actions,
    }


    return decision, escalation_record