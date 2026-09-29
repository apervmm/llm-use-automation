"""
The one place an action is carried out. Discovery and replay both call
execute(); they differ only in how the target was chosen and how the result
is judged.

Policy (allowlist and permitted action types) is enforced inside the
surface's own methods, so it applies here without being repeated.
"""
from surface.browser import BrowserSession
from surface.types import ActionResult
from .types import Action, ActionKind

NEEDS_TARGET = {ActionKind.CLICK, ActionKind.TYPE_TEXT, ActionKind.SELECT_OPTION, ActionKind.READ}
NEEDS_VALUE = {ActionKind.NAVIGATE, ActionKind.TYPE_TEXT, ActionKind.SELECT_OPTION}


def execute(session: BrowserSession, action: Action) -> ActionResult:
    if problem := _malformed(action):
        return ActionResult(False, action.kind.value, action.description, error=problem)

    result = _dispatch(session, action)
    dialogs = session.pop_dialogs()
    if dialogs and result.success:
        return ActionResult(
            False, 
            result.action, 
            result.target_description,
            error=f"Unexpected dialog(s) dismissed: {dialogs}"
        )
    return result


def _malformed(action: Action) -> str | None:
    if action.kind in NEEDS_TARGET and action.target is None:
        return f"{action.kind.value} needs a target element"
    if action.kind in NEEDS_VALUE and action.value is None:
        return f"{action.kind.value} needs a value"
    return None


def _dispatch(session: BrowserSession, action: Action) -> ActionResult:
    match action.kind:
        case ActionKind.NAVIGATE:
            return session.goto(action.value)
        case ActionKind.CLICK:
            return session.click(action.target, description=action.description)
        case ActionKind.TYPE_TEXT:
            return session.type_text(action.target, action.value, description=action.description)
        case ActionKind.SELECT_OPTION:
            return session.select_option(action.target, action.value, description=action.description)
        case ActionKind.READ:
            return session.read_text(action.target, description=action.description)