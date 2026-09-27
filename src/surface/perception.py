from pathlib import Path

from .types import PageState, InteractiveElement, ElementRef, LocatorStrategy
from .browser import BrowserSession
from .helpers import to_interactive_element, trimmed_text



_SCRIPT_PATH = Path(__file__).parent / "scripts" / "extract_elements.js"
_EXTRACT_JS = _SCRIPT_PATH.read_text()
_ROLE_TO_ELEMENT_TYPE = {
    "button": "button", "link": "link", "textbox": "textbox",
    "checkbox": "checkbox", "radio": "checkbox", "combobox": "select",
}


def snapshot(session: BrowserSession, screenshot_path: str | None = None) -> PageState:
    """
    builds a PageState = the interactive elements + visible text + a screenshot
    """
    page = session.page
    elements = [to_interactive_element(item) for item in page.evaluate(_EXTRACT_JS)]
    shot_path = session.screenshot(screenshot_path) if screenshot_path else None

    return PageState(
        url=page.url,
        title=page.title(),
        interactive_elements=elements,
        visible_text_summary=trimmed_text(page),
        screenshot_path=shot_path,
    )
