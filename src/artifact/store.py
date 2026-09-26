import re
from pathlib import Path
from .schema import Capability
from .helpers import artifact_filename, artifact_files, existing_versions, safe_path, validate_id, version_of

DEFAULT_APP = "parabank"


ARTIFACT_DIR = Path("artifacts")

_VALID_ID = re.compile(r"^[a-zA-Z0-9_.-]+$")


def _validate_id(capability_id: str) -> None:
    if not _VALID_ID.match(capability_id):
        raise ValueError(
            f"Invalid capability_id: {capability_id!r}. "
            "Only letters, digits, '.', '_', '-' are allowed."
        )


def _safe_path(filename: str) -> Path:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    base = ARTIFACT_DIR.resolve()
    candidate = (ARTIFACT_DIR / filename).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError(f"Resolved path {candidate} escapes artifact directory.")
    return candidate


def _existing_versions(capability_id: str) -> list[int]:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    versions = []
    for p in ARTIFACT_DIR.glob(f"{capability_id}.v*.json"):
        match = re.search(r"\.v(\d+)\.json$", p.name)
        if match:
            versions.append(int(match.group(1)))
    return versions


def qualify(capability_id: str, target_app: str = DEFAULT_APP) -> str:
    prefix = f"{target_app}."
    return capability_id if capability_id.startswith(prefix) else prefix + capability_id


def save(capability: Capability) -> Path:
    capability.capability_id = qualify(capability.capability_id, capability.target_app)
    _validate_id(capability.capability_id)
    existing = _existing_versions(capability.capability_id)
    if existing and capability.version <= max(existing):
        capability.version = max(existing) + 1
    path = _safe_path(f"{capability.capability_id}.v{capability.version}.json")
    path.write_text(capability.model_dump_json(indent=2))
    return path


def load(capability_id: str, version: int | None = None) -> Capability:
    capability_id = qualify(capability_id)
    _validate_id(capability_id)

    if version is not None:
        filename = f"{capability_id}.v{version}.json"
        path = _safe_path(filename)
        return Capability.model_validate_json(path.read_text())

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    candidates = list(ARTIFACT_DIR.glob(f"{capability_id}.v*.json"))
    if not candidates:
        raise FileNotFoundError(f"No artifact found for {capability_id}")

    def version_num(p: Path) -> int:
        match = re.search(r"\.v(\d+)\.json$", p.name)
        return int(match.group(1)) if match else -1

    latest = max(candidates, key=version_num)
    return Capability.model_validate_json(latest.read_text())