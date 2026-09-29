from dataclasses import dataclass, field
from enum import Enum

from surface.types import ElementRef


class ActionKind(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE_TEXT = "type_text"
    SELECT_OPTION = "select_option"
    READ = "read"


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    target: ElementRef | None = None
    value: str | None = field(default=None, repr=False)
    description: str = ""