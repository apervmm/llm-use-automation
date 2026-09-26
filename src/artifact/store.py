import re
from pathlib import Path
from .schema import Capability
from .helpers import artifact_filename, artifact_files, existing_versions, safe_path, validate_id, version_of

DEFAULT_APP = "parabank"
ARTIFACT_DIR = Path("artifacts")


def qualify(capability_id: str, target_app: str = DEFAULT_APP) -> str:
    prefix = f"{target_app}."
    return capability_id if capability_id.startswith(prefix) else prefix + capability_id


def save(capability: Capability) -> Path:
    capability.capability_id = qualify(capability.capability_id, capability.target_app)
    validate_id(capability.capability_id)
    existing = existing_versions(ARTIFACT_DIR, capability.capability_id)
    if existing and capability.version <= max(existing):
        capability.version = max(existing) + 1
    path = safe_path(ARTIFACT_DIR, artifact_filename(capability.capability_id, capability.version))
    path.write_text(capability.model_dump_json(indent=2))
    return path


def load(capability_id: str, version: int | None = None) -> Capability:
    capability_id = qualify(capability_id)
    validate_id(capability_id)
    if version is not None:
        path = safe_path(ARTIFACT_DIR, artifact_filename(capability_id, version))
        return Capability.model_validate_json(path.read_text())
    candidates = artifact_files(ARTIFACT_DIR, capability_id)
    if not candidates:
        raise FileNotFoundError(f"No artifact found for {capability_id}")
    latest =  max(candidates, key=version_of)
    return Capability.model_validate_json(latest.read_text())