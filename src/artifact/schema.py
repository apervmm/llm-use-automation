from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field

from surface.types import ElementRef


class ParamType(str, Enum):
    STRING = "string"
    NUMBER = "number"


class InputParam(BaseModel):
    name: str                         
    type: ParamType = ParamType.STRING
    description: str = ""
    required: bool = True
    example: Optional[str] = None


class OutputField(BaseModel):
    name: str                         
    type: ParamType = ParamType.STRING
    description: str = ""
    source_label: str = ""    
    derived_from_outcome: bool = False         


class StepAction(str, Enum):
    CLICK = "click"
    TYPE_TEXT = "type_text"
    NAVIGATE = "navigate"
    READ = "read"
    SELECT_OPTION = "select_option"


class Step(BaseModel):
    step_num: int
    action: StepAction
    target: Optional[ElementRef] = None # None = navigate
    value: Optional[str] = None   # "{param_name}" 
    read_label: Optional[str] = None  # for READ steps, maps to an OutputField
    description: str = ""                 


class Checkpoint(BaseModel):
    kind: Literal["url_contains", "element_visible", "text_visible"]
    expected: str      


class OutcomeRule(BaseModel):
    name: str    # ex invalid credentials
    kind: Literal["text_visible", "url_contains"]
    expected: str
    description: str = ""                        

class RiskLevel(str, Enum):
    SAFE = "safe"
    RISKY = "risky"

class Capability(BaseModel):
    capability_id: str                     
    version: int = 1
    description: str = ""
    target_app: str = "parabank"
    entry_url: str

    inputs: list[InputParam] = Field(default_factory=list)
    outputs: list[OutputField] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    checkpoint: Optional[Checkpoint] = None

    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: Literal["llm_discovery"] = "llm_discovery"
    outcome_rules: list[OutcomeRule] = Field(default_factory=list)

    risk_level: RiskLevel = RiskLevel.SAFE

