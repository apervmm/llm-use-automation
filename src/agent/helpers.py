from typing import Any

from surface.browser import BrowserSession
from surface.perception import snapshot
from surface.types import ElementRef, PageState


# ---------- Observing page -------------
def take_snapshot(session: BrowserSession, evidence_dir: str, name: str) -> PageState:
    return snapshot(session, screenshot_path=f"{evidence_dir}/{name}.png")


def observation_text(goal: str | None, state: PageState, include_goal: bool = True) -> str:
    """The page as the model sees it: URL, title, named elements, and some text"""
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


# ---------- Conversation turns ----------
def user_turn(content: str) -> dict:
    return {"role": "user", "content": content}


def tool_result_turn(tool_use_id: str, text: str) -> dict:
    return {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": text}]}


def first_tool_use(response) -> Any | None:
    """The model's tool call, or None if it answered without one."""
    return next((b for b in response.content if b.type == "tool_use"), None)


# ---------- Acting ----------
def _not_found(state: PageState, kind: str, element_name: str) -> tuple[str, PageState, None, bool]:
    return f"ERROR: no {kind} named '{element_name}' found on this page.", state, None, False


def execute_tool(
    session: BrowserSession, tool_use, state: PageState, step_num: int, evidence_dir: str,
) -> tuple[str, PageState, ElementRef | None, bool]:
    """
    Carry out one tool call on the page
    Returns text for the model, page state afterwards, element used, success
    """
    name, inp = tool_use.name, tool_use.input

    if name == "click":
        ref = state.find_ref(inp["element_name"], inp.get("role"))
        if ref is None:
            return _not_found(state, "element", inp["element_name"])
        result = session.click(ref, description=inp["element_name"])
    elif name == "type_text":
        ref = state.find_ref(inp["element_name"], "textbox")
        if ref is None:
            return _not_found(state, "textbox", inp["element_name"])
        result = session.type_text(ref, inp["text"], description=inp["element_name"])
    elif name == "navigate":
        ref = None
        result = session.goto(inp["url"])
    elif name == "select_option":
        ref = state.find_ref(inp["element_name"], "combobox")
        if ref is None:
            return _not_found(state, "dropdown", inp["element_name"])
        result = session.select_option(ref, inp["option_value"], description=inp["element_name"])
    elif name == "read":
        ref = state.find_ref(inp["element_name"]) if inp.get("element_name") else None
        return f"Recorded {inp['label']} = {inp['value']}.", state, ref, True
    else:
        return f"ERROR: unknown tool '{name}'.", state, None, False

    if not result.success:
        return f"ERROR: {name} failed — {result.error}", state, ref, False

    session.wait(500)
    new_state = take_snapshot(session, evidence_dir, f"step_{step_num}")
    return f"{name} succeeded. New page: {observation_text(None, new_state, include_goal=False)}", new_state, ref, True