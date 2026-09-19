SYSTEM_PROMPT = """
You are an automation agent operating a bank employee's web application \
to accomplish a stated goal. You can only see and act on elements explicitly listed under \
"Interactive elements" for the current page — you cannot invent elements that aren't listed.

Rules:
- Choose exactly ONE tool call per turn. Never explain in prose; always call a tool.
- Prefer the exact element name shown to you, verbatim.
- Use `read` to record any data the goal asks you to extract (e.g. a balance), without it
  being a click or type action.
- Once the goal is fully achieved, call `done` and include any requested values in `outputs`.
- If an action fails (reported back to you as an error), do not repeat the identical action —
  try an alternative element or approach based on the new page state.
"""

TOOLS = [
    {
        "name": "click",
        "description": "Click a button, link, or checkbox on the current page, identified by its visible accessible name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "element_name": {"type": "string"},
                "role": {"type": "string", "enum": ["button", "link", "checkbox", "combobox"]},
            },
            "required": ["element_name", "role"],
        },
    },
    {
        "name": "type_text",
        "description": "Type text into a textbox on the current page, identified by its visible accessible name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "element_name": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["element_name", "text"],
        },
    },
    {
        "name": "navigate",
        "description": "Navigate directly to a URL.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "select_option",
        "description": "Select an option from a dropdown (<select>) on the current page, identified by its visible accessible name. option_value must be one of that dropdown's listed option values.",
        "input_schema": {
            "type": "object",
            "properties": {
                "element_name": {"type": "string"},
                "option_value": {"type": "string"},
            },
            "required": ["element_name", "option_value"],
        },
    },
    {
        "name": "read",
        "description": "Record a piece of data observed on the page (e.g. an account balance). Does not act on the browser.",
        "input_schema": {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "value": {"type": "string"},
                "element_name": {
                        "type": "string", 
                        "description": "The visible element this value was read from — always try to provide this so the value can be re-located during replay."
                    },
            },
            "required": ["label", "value", "element_name"],
        },
    },
    {
        "name": "done",
        "description": "Call once the goal is fully achieved. Include any requested values.",
        "input_schema": {
            "type": "object",
            "properties": {
                "outputs": {"type": "object", "additionalProperties": {"type": "string"}}
            },
        },
    },
]