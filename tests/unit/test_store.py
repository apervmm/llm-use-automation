"""Artifact store: qualified ids, versioning, and safe file names."""
import pytest

from artifact import store
from artifact.schema import Capability

URL = "http://localhost:8080/parabank/index.htm"


def test_short_id_gets_the_app_prefix():
    assert store.qualify("request_loan") == "parabank.request_loan"


def test_qualified_id_is_left_unchanged():
    assert store.qualify("parabank.request_loan") == "parabank.request_loan"


def test_save_uses_the_qualified_id_in_file_name_and_content(artifact_dir):
    path = store.save(Capability(capability_id="login", entry_url=URL))
    assert path.name == "parabank.login.v1.json"
    assert store.load("parabank.login").capability_id == "parabank.login"


def test_load_accepts_the_short_id(artifact_dir):
    store.save(Capability(capability_id="login", entry_url=URL))
    assert store.load("login").capability_id == "parabank.login"


def test_saving_again_creates_the_next_version(artifact_dir):
    store.save(Capability(capability_id="login", entry_url=URL))
    second = store.save(Capability(capability_id="login", entry_url=URL))
    assert second.name == "parabank.login.v2.json"
    assert store.load("login").version == 2
    assert store.load("login", version=1).version == 1


def test_loading_an_unknown_capability_raises(artifact_dir):
    with pytest.raises(FileNotFoundError):
        store.load("does_not_exist")


def test_ids_that_could_escape_the_folder_are_rejected(artifact_dir):
    with pytest.raises(ValueError):
        store.load("../secrets")