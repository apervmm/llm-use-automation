from pathlib import Path
from .helpers import load_policy_config, matches_any, resolve_allowed_domains, split_url


_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "allowlist.yaml"


class PolicyViolation(Exception):
    """Raised when an action or capability falls outside the configured policy"""


class Allowlist:
    def __init__(self, config_path: Path = _CONFIG_PATH):
        config = load_policy_config(config_path or _CONFIG_PATH)
        self.allowed_domains = resolve_allowed_domains(config)
        self.allowed_routes = config.get("allowed_routes", [])
        self.allowed_actions = set(config.get("allowed_actions", []))
        self.blocked_actions = set(config.get("blocked_actions", []))
        self.risky_patterns = config.get("risky_capability_patterns", [])


    def check_action(self, action: str, url: str | None = None) -> None:
        """called before every browser action, raises PolicyViolation if disallowed"""
        if action in self.blocked_actions:
            raise PolicyViolation(f"Action '{action}' is explicitly blocked by policy.")
        if action not in self.allowed_actions:
            raise PolicyViolation(f"Action '{action}' is not in the allowed action list.")
        if url:
            self.check_url(url)


    def check_url(self, url: str) -> None:
        """Raises PolicyViolation if the URL's domain or route is outside the allowlist"""
        domain, path = split_url(url)
        if domain and domain not in self.allowed_domains:
            raise PolicyViolation(f"Domain '{domain}' is not in the allowlist.")
        if self.allowed_routes and not matches_any(path, self.allowed_routes):
            raise PolicyViolation(f"Route '{path}' is not in the allowed routes.")


    def is_risky(self, capability_id: str) -> bool:
        return matches_any(capability_id, self.risky_patterns)