import fnmatch
import yaml
from pathlib import Path
from urllib.parse import urlparse

import os


_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "allowlist.yaml"


class PolicyViolation(Exception):
    """Raised when an action or capability falls outside the configured policy"""


class Allowlist:
    def __init__(self, config_path: Path = _CONFIG_PATH):
        path = config_path or _CONFIG_PATH
        config = yaml.safe_load(path.read_text())

        base_url = os.environ.get("PARABANK_BASE_URL")
        if base_url:
            self.allowed_domains = [urlparse(base_url).netloc]
        else:
            self.allowed_domains = config.get("allowed_domains", [])

        # self.allowed_domains = config.get("allowed_domains", [])s
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
            self._check_url(url)


    def _check_url(self, url: str) -> None:
        parsed = urlparse(url)
        domain = parsed.netloc
        if domain and domain not in self.allowed_domains:
            raise PolicyViolation(f"Domain '{domain}' is not in the allowlist.")
        path = parsed.path or "/"
        if self.allowed_routes and not any(
            fnmatch.fnmatch(path, pattern) for pattern in self.allowed_routes
        ):
            raise PolicyViolation(f"Route '{path}' is not in the allowed routes.")


    def is_risky(self, capability_id: str) -> bool:
        return any(fnmatch.fnmatch(capability_id, pattern) for pattern in self.risky_patterns)