from .types import PageState, InteractiveElement, ElementRef, LocatorStrategy
from .browser import BrowserSession


from pathlib import Path



_SCRIPT_PATH = Path(__file__).parent / "scripts" / "extract_elements.js"
_EXTRACT_JS = _SCRIPT_PATH.read_text()
_ROLE_TO_ELEMENT_TYPE = {
    "button": "button", "link": "link", "textbox": "textbox",
    "checkbox": "checkbox", "radio": "checkbox", "combobox": "select",
}


def snapshot(session: BrowserSession, screenshot_path: str | None = None) -> PageState:
    page = session.page
    raw_elements = page.evaluate(_EXTRACT_JS)

    elements: list[InteractiveElement] = []
    seen = set()
    for item in raw_elements:
        role, name, css = item["role"], item["name"], item["cssSelector"]


        key = (role, name)
        if key in seen:
            continue
        seen.add(key)

        is_stable_css = css.startswith("#") or "[name=" in css

        role_ref = ElementRef(LocatorStrategy.ROLE_NAME, value=name, role=role, expected_name=name)
        css_ref = ElementRef(LocatorStrategy.CSS, value=css, role=role, expected_name=name)
        text_ref = (
            ElementRef(LocatorStrategy.TEXT, value=name, expected_name=name)
            if role in ("link", "button") else None
        )

        if is_stable_css:
            primary, chain = css_ref, [role_ref, text_ref]
        else:
            primary, chain = role_ref, [text_ref, css_ref]

        primary.fallbacks = [r for r in chain if r]
        ref = primary


        # fallbacks = [ElementRef(strategy=LocatorStrategy.ROLE_NAME, value=name, role=role)]


        # if role in ("link", "button"):
        #     fallbacks.append(ElementRef(strategy=LocatorStrategy.TEXT, value=name))

        # ref = ElementRef(
        #     strategy=LocatorStrategy.CSS,
        #     value=css,
        #     role=role,
        #     fallbacks=fallbacks
        # )

        
        elements.append(InteractiveElement(
            ref=ref,
            role=role,
            accessible_name=name,
            element_type=_ROLE_TO_ELEMENT_TYPE.get(role, "other"),
            options=item.get("options", []),
        ))

    shot_path = session.screenshot(screenshot_path) if screenshot_path else None

    return PageState(
        url=page.url,
        title=page.title(),
        interactive_elements=elements,
        visible_text_summary=_trimmed_text(page),
        screenshot_path=shot_path,
    )


def _trimmed_text(page, max_chars: int = 2000) -> str:
    return page.inner_text("body")[:max_chars]