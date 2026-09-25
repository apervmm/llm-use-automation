"""Artifact schema rules that apply when an artifact is created or loaded."""
import pytest
from pydantic import ValidationError

from artifact.schema import Capability, InputParam, OutputField, ParamType, Step, StepAction

URL = "http://localhost:8080/parabank/index.htm"


def test_duplicate_step_numbers_are_rejected():
    with pytest.raises(ValidationError, match="Duplicate step_num"):
        Capability(
            capability_id="parabank.example",
            entry_url=URL,
            steps=[Step(step_num=1, action=StepAction.CLICK), Step(step_num=1, action=StepAction.CLICK)],
        )


def test_inputs_and_outputs_default_to_string():
    assert InputParam(name="username").type == ParamType.STRING
    assert OutputField(name="message").type == ParamType.STRING


def test_artifact_survives_a_save_and_load_round_trip(loan_capability):
    restored = Capability.model_validate_json(loan_capability.model_dump_json())
    assert restored == loan_capability