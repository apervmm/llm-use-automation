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


def to_operator(request: EscalationRequest, state: HandoffState, evidence_dir: str = "evidence/escalations") -> OperatorDecision:
    print(f"Reason: {request.reason.value}")
    print(f"Task: {request.capability_or_goal}")
    print(f"Step:  {request.current_step}")
    print(f"Current URL: {request.current_url}")
    print(f"Detail: {request.detail}")
    # print()
    # print(_GUIDANCE.get(request.reason, "resume -> proceed. abort -> stop here."))
    # print()

    
    # action_note = input(
    #     "Describe what you did"
    #     "[type `abort` = stops the run or `enter` = to submit a note or skip]: "
    # )

    # decision = OperatorDecision.ABORT if action_note.strip().lower() == "abort" else OperatorDecision.RESUME
    # decision = OperatorDecision.ABORT if raw == "abort" else OperatorDecision.RESUME



    while True:
        raw = input("Type 'resume' or 'abort': ").strip().lower()
        if raw == "resume":
            decision = OperatorDecision.RESUME
            break
        if raw == "abort":
            decision = OperatorDecision.ABORT
            break
        print("Please type exactly 'resume' or 'abort' — try again.")


    if decision == OperatorDecision.RESUME:
        print("Resuming...\n")
        note = input("Optional note for the record (press Enter to skip): ").strip()
        if note:
            state.record_human_action(note)
        state.resume_automation()
    else:
        print("Aborting run at operator's request...\n")

    # if decision == OperatorDecision.RESUME:
    #     if action_note.strip():
    #         state.record_human_action(action_note.strip())
    #     state.resume_automation()
    #     print("Resuming...\n")
    # else:
    #     print("Aborting run at operator's request...\n")


    Path(evidence_dir).mkdir(parents=True, exist_ok=True)
    record_path = Path(request.evidence_dir) / f"escalation_{uuid.uuid4().hex}.json"
    record_path.write_text(json.dumps({
        "reason": request.reason.value,
        "run_id": request.run_id,
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