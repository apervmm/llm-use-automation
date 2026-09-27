
import fnmatch
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import yaml


#  ------------ Allowlist ----------------------
def load_policy_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def resolve_allowed_domains(config: dict) -> list[str]:
    base_url = os.environ.get("PARABANK_BASE_URL")
    if base_url:
        return [urlparse(base_url).netloc]
    return config.get("allowed_domains", [])


def split_url(url: str) -> tuple[str, str]:
    """Return (domain, path). An empty path counts as '/'."""
    parsed = urlparse(url)
    return parsed.netloc, parsed.path or "/"


def matches_any(value: str, patterns: list[str]) -> bool:
    """True if value matches at least one glob pattern"""
    return any(fnmatch.fnmatch(value, pattern) for pattern in patterns)



#  ------------ Redaction ----------------------
REDACTED = "[REDACTED]"
SECRET_KEYS = frozenset({"password", "pin", "ssn"})

PII_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED-SSN]"),
    (re.compile(r"\b\d{13,19}\b"), "[REDACTED-CARD-OR-ACCOUNT]"),
]


def mask_account(value) -> str:
    """Keeps last digits '13344' -> '***44'."""
    s = str(value)
    return "*" * (len(s) - 2) + s[-2:] if len(s) > 2 else "*" * len(s)


def field_replacement(key: str, value, element_name: str) -> str | None:
    """
    The recursively redacted form of one dict field, or None when no field rule applies

    element_name =  {"element_name": "Password", "text": "demo"},
    the secret are generic "text" key.
    """
    key_lower = key.lower()
    element = element_name.lower()
    looks_numeric = str(value).isdigit()

    if key_lower in SECRET_KEYS:
        return REDACTED
    if key == "text" and any(secret in element for secret in SECRET_KEYS):
        return REDACTED
    if key in ("text", "option_value") and "account" in element and looks_numeric:
        return mask_account(value)
    if "account" in key_lower and looks_numeric:
        return mask_account(value)
    return None


def replace_known_values(text: str, sensitive_values: set[str], masked_values: set[str]) -> str:
    for secret in sensitive_values:
        if secret:
            text = text.replace(secret, REDACTED)
    for account in masked_values:
        if account:
            # The digit lookarounds stop '13344' being masked inside '133445'.
            text = re.sub(rf"(?<!\d){re.escape(account)}(?!\d)", mask_account(account), text)
    return text