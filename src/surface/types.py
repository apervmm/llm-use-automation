from dataclasses import dataclass, field
from typing import Literal, Optional
from enum import Enum



class LocatorStrategy(str, Enum):
    ROLE_NAME = "role_name"      
    CSS = "css"                 
    TEXT = "text"               
    XPATH = "xpath"          


@dataclass
class ElementRef:
    strategy: LocatorStrategy
    value: str                     
    role: Optional[str] = None     
    expected_name: Optional[str] = None
    fallbacks: list["ElementRef"] = field(default_factory=list)


@dataclass
class InteractiveElement:
    ref: ElementRef
    role: str
    accessible_name: str
    element_type: Literal["button", "link", "textbox", "select", "checkbox", "other"]
    is_visible: bool = True
    options: list[str] = field(default_factory=list) 


@dataclass
class PageState:
    """What the agent 'sees' at one point in time."""
    url: str
    title: str
    interactive_elements: list[InteractiveElement]
    visible_text_summary: str      
    screenshot_path: Optional[str] = None   

    def find_ref(self, name: str, role: str | None = None) -> Optional["ElementRef"]:
        name_lower = name.strip().lower()

        def role_ok(el: "InteractiveElement") -> bool:
            return role is None or el.role == role or el.element_type == role

        for el in self.interactive_elements:
            if el.accessible_name.strip().lower() == name_lower and role_ok(el):
                return el.ref

        for el in self.interactive_elements:
            if name_lower in el.accessible_name.strip().lower() and role_ok(el):
                return el.ref

        return None
    
    
        # name_lower = name.strip().lower()
        # for el in self.interactive_elements:
        #     if el.accessible_name.strip().lower() == name_lower:
        #         if role is None or el.role == role or el.element_type == role:
        #             return el.ref
                
        # for el in self.interactive_elements:
        #     if name_lower in el.accessible_name.strip().lower():
        #         return el.ref
            
        # return None


    # types.py — new method
    # def find_text(self, label: str) -> Optional["ElementRef"]:
    #     return ElementRef(strategy=LocatorStrategy.TEXT, value=label, expected_name=label)



@dataclass
class ActionResult:
    success: bool
    action: str     # click | type |navigate | read
    target_description: str         # for logs
    error: Optional[str] = None
    duration_ms: int = 0
    value: Optional[str] = None 


