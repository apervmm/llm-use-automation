import re
from .helpers import PII_PATTERNS, field_replacement, replace_known_values


def redact_any(obj, sensitive_values: set[str] | None = None,  masked_values: set[str] | None = None):
    """
    Recursively redacts a nested structure (dict/list/str) before serialization.
    
    - Any dict value whose KEY name matches a known-sensitive field (password, pin, ssn) is redacted regardless of nesting depth
    - Any string value exactly matching a known sensitive literal  is redacted, so it's caught even when embedded in free text like a goal string or a page-state dump.
    """
    sensitive_values = sensitive_values or set()
    masked_values = masked_values or set()

    if isinstance(obj, dict):
        element_name = str(obj.get("element_name", ""))
        out = {}
        for key, value in obj.items():
            replacement = field_replacement(key, value, element_name)
            out[key] = replacement if replacement is not None else redact_any(value, sensitive_values, masked_values)
        return out

    if isinstance(obj, list):
        return [redact_any(item, sensitive_values, masked_values) for item in obj]

    if isinstance(obj, str):
        return replace_known_values(redact(obj), sensitive_values, masked_values)
    
    return obj


def redact(text: str) -> str:
    for pattern, replacement in PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text
