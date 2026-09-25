import pytest

from artifact.store import qualify
from safety.allowlist import Allowlist, PolicyViolation

TEST_POLICY = """
allowed_domains: [localhost:8080]
allowed_routes: ["/parabank/index.htm", "/parabank/login.htm*"]
allowed_actions: [click, type_text, navigate, read, select_option]
blocked_actions: [download]
risky_capability_patterns: ["*.request_loan"]
"""


@pytest.fixture
def policy(tmp_path, monkeypatch) -> Allowlist:
    """An allowlist from a test config, unaffected by PARABANK_BASE_URL."""
    monkeypatch.delenv("PARABANK_BASE_URL", raising=False)
    path = tmp_path / "allowlist.yaml"
    path.write_text(TEST_POLICY)
    return Allowlist(config_path=path)


def test_allowed_action_on_an_allowed_page_passes(policy):
    policy.check_action("click", url="http://localhost:8080/parabank/index.htm")


def test_route_patterns_ignore_query_strings(policy):
    policy.check_action("click", url="http://localhost:8080/parabank/login.htm?jsessionid=1")


def test_page_outside_the_allowed_routes_is_blocked(policy):
    with pytest.raises(PolicyViolation, match="Route"):
        policy.check_action("click", url="http://localhost:8080/parabank/about.htm")


def test_other_domains_are_blocked(policy):
    with pytest.raises(PolicyViolation, match="Domain"):
        policy.check_action("navigate", url="http://evil.example/parabank/index.htm")


def test_explicitly_blocked_action_is_refused(policy):
    with pytest.raises(PolicyViolation, match="explicitly blocked"):
        policy.check_action("download")


def test_action_missing_from_the_allowed_list_is_refused(policy):
    with pytest.raises(PolicyViolation, match="not in the allowed action list"):
        policy.check_action("drag")


def test_base_url_setting_replaces_the_allowed_domains(tmp_path, monkeypatch):
    monkeypatch.setenv("PARABANK_BASE_URL", "http://tenant.example:9000")
    path = tmp_path / "allowlist.yaml"
    path.write_text(TEST_POLICY)
    assert Allowlist(config_path=path).allowed_domains == ["tenant.example:9000"]


def test_loan_request_is_risky_in_the_real_config():
    assert Allowlist().is_risky("parabank.request_loan")


def test_login_is_not_risky_in_the_real_config():
    assert not Allowlist().is_risky("parabank.login")


def test_short_id_only_matches_risk_patterns_once_qualified():
    # '*.request_loan' needs the 'parabank.' prefix to match.
    assert not Allowlist().is_risky("request_loan")
    assert Allowlist().is_risky(qualify("request_loan"))