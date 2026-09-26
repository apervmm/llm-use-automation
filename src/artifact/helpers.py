from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from safety.redaction import is_secret_name
from .schema import InputParam, OutputField, ParamType, Step, StepAction

if TYPE_CHECKING:
    # saving a file shouldn't pull in the agent and playwright at runtime.
    from agent.loop import TranscriptStep


# ----------- Recorder: transcript -> steps -----------
def build_steps(transcript: list[TranscriptStep], param_map: dict[str, str]) -> list[Step]:
    """
        Successful actions become steps numbered 1..n
        failed actions and 'done' are left out
    """
    steps: list[Step] = []
    for t in transcript:
        if not t.success or t.tool_name == "done":
            continue
        step = to_step(t, len(steps) + 1, param_map)
        if step:
            steps.append(step)
    return steps


def to_step(t: TranscriptStep, step_num: int, param_map: dict[str, str]) -> Step | None:
    """One agent action as a replayable Step, or None for tools that aren't replayed"""
    tool, inp = t.tool_name, t.tool_input
    element = inp.get("element_name")

    if tool == "read":
        return Step(
            step_num=step_num,
            action=StepAction.READ,
            target=t.resolved_ref,  # None if the LLM didn't name an element
            read_label=inp.get("label"),
            description=f"Read '{inp.get('label')}'",
        )
    if tool == "click":
        return Step(
            step_num=step_num,
            action=StepAction.CLICK,
            target=t.resolved_ref,
            description=f"Click '{element}'",
        )
    if tool == "type_text":
        return Step(
            step_num=step_num,
            action=StepAction.TYPE_TEXT,
            target=t.resolved_ref,
            value=parameterize(inp.get("text", ""), param_map),
            description=f"Type into '{element}'",
        )
    if tool == "select_option":
        value = parameterize(inp.get("option_value", ""), param_map)
        return Step(
            step_num=step_num,
            action=StepAction.SELECT_OPTION,
            target=t.resolved_ref,
            value=value,
            description=f"Select '{value}' in '{element}'",
        )
    if tool == "navigate":
        return Step(
            step_num=step_num,
            action=StepAction.NAVIGATE,
            value=inp.get("url"),
            description=f"Navigate to {inp.get('url')}",
        )
    return None


def parameterize(literal: str, param_map: dict[str, str]) -> str:
    """'john' -> '{username}' when 'john' is a recorded param; anything else unchanged"""
    return f"{{{param_map[literal]}}}" if literal in param_map else literal


def unmatched_params(steps: list[Step], param_map: dict[str, str]) -> list[str]:
    """Param names no step refers to the literal was never typed or selected"""
    return [
        name for name in param_map.values()
        if not any(s.value and f"{{{name}}}" in s.value for s in steps)
    ]


def template(text: str, param_map: dict[str, str]) -> str:
    """Replaces recorded literals in free text with {param} placeholders, longest first"""
    for literal in sorted(param_map, key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(literal)}(?!\w)", "{" + param_map[literal] + "}", text)
    return text


# ----------- Recorder: inputs and outputs -----------
def infer_type(literal: str) -> ParamType:
    """'1000' -> NUMBER, 'demo' -> STRING based on the value the agent used"""
    try:
        float(literal)
        return ParamType.NUMBER
    except ValueError:
        return ParamType.STRING


def build_inputs(param_map: dict[str, str]) -> list[InputParam]:
    """OSecret params never keep their example value"""
    return [
        InputParam(
            name=name,
            type=infer_type(literal),
            example="[REDACTED]" if is_secret_name(name) else literal,
        )
        for literal, name in param_map.items()
    ]


def build_outputs(output_keys: list[str], run_outputs: dict, outcome_derived: list[str]) -> list[OutputField]:
    """The declared outputs the run actually produced and what derived from the outcome"""
    return [
        OutputField(name=key, source_label=key, derived_from_outcome=(key in outcome_derived))
        for key in output_keys
        if key in run_outputs or key in outcome_derived
    ]


# ----------- Store: ids, file names and versions -----------
_VALID_ID = re.compile(r"^[a-zA-Z0-9_.-]+$")
_VERSION_IN_NAME = re.compile(r"\.v(\d+)\.json$")


def validate_id(capability_id: str) -> None:
    if not _VALID_ID.match(capability_id):
        raise ValueError(
            f"Invalid capability_id: {capability_id!r}. "
            "Only letters, digits, '.', '_', '-' are allowed."
        )
    

def artifact_filename(capability_id: str, version: int) -> str:
    return f"{capability_id}.v{version}.json"


def safe_path(folder: Path, filename: str) -> Path:
    """The file's path inside folder; raises if the name would escape"""
    folder.mkdir(parents=True, exist_ok=True)
    base = folder.resolve()
    candidate = (folder / filename).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError(f"Resolved path {candidate} escapes artifact directory.")
    return candidate


def version_of(path: Path) -> int:
    """outputs the version number, -1 if the name has no version"""
    match = _VERSION_IN_NAME.search(path.name)
    return int(match.group(1)) if match else -1


def artifact_files(folder: Path, capability_id: str) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    return list(folder.glob(f"{capability_id}.v*.json"))


def existing_versions(folder: Path, capability_id: str) -> list[int]:
    return [v for v in map(version_of, artifact_files(folder, capability_id)) if v >= 0]