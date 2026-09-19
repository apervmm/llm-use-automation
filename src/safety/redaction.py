import re

# Not exhaustive PII detection
# Goal: never let credentials or account-like numbers persist verbatim into artifacts or logs

_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED-SSN]"),
    (re.compile(r"\b\d{13,19}\b"), "[REDACTED-CARD-OR-ACCOUNT]"),
]

_SENSITIVE_KEYS = {"password", "pin", "ssn", "text"}


def redact_any(obj, sensitive_values: set[str] | None = None):
    """
    Recursively redact a nested structure (dict/list/str) before
    serialization. Two mechanisms combine:
    - Any dict value whose KEY name matches a known-sensitive field
      (password, pin, ssn) is redacted regardless of nesting depth.
    - Any string value exactly matching a known sensitive literal
      (e.g. a specific password value passed in) is redacted, so it's
      caught even when embedded in free text like a goal string or a
      page-state dump.
    """
    sensitive_values = sensitive_values or set()

    if isinstance(obj, dict):
        out = {}
        # special case: {"element_name": "Password", "text": "demo"} —
        # the sensitive value sits under a generic "text" key.
        el_name = str(obj.get("element_name", "")).lower()
        text_is_sensitive = any(k in el_name for k in ("password", "pin", "ssn"))
        for k, v in obj.items():
            if k.lower() in ("password", "pin", "ssn"):
                out[k] = "[REDACTED]"
            elif k == "text" and text_is_sensitive:
                out[k] = "[REDACTED]"
            else:
                out[k] = redact_any(v, sensitive_values)
        return out

    if isinstance(obj, list):
        return [redact_any(v, sensitive_values) for v in obj]

    if isinstance(obj, str):
        result = redact(obj)  # existing pattern-based scrub (SSN/card shapes)
        for val in sensitive_values:
            if val:
                result = result.replace(val, "[REDACTED]")
        return result

    return obj


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_dict(d: dict, sensitive_keys: set[str] = frozenset({"password", "ssn", "pin"})) -> dict:
    out = {}
    for k, v in d.items():
        if k.lower() in sensitive_keys:
            out[k] = "[REDACTED]"
        elif isinstance(v, str):
            out[k] = redact(v)
        else:
            out[k] = v
    return out