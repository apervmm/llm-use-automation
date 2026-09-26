from .helpers import ask_decision, ask_note, escalation_record, print_request
from .types import EscalationRequest, HandoffState, OperatorDecision



def to_operator(request: EscalationRequest, state: HandoffState) -> OperatorDecision:
    print_request(request)
    decision = ask_decision()
    human_actions: list[str] = []
    if decision == OperatorDecision.RESUME:
        print("Resuming...\n")
        human_actions = ask_note()
        state.resume_automation()
    else:
        print("Aborting run at operator's request...\n")

    return decision,  escalation_record(request, decision, human_actions)