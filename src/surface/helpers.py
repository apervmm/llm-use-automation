"""
turning locators into live elements
building locator chains, 
assembling ActionResults

Used only by browser.py and perception.py.
"""
import time

from playwright.sync_api import Locator, Page, Request

from safety.allowlist import Allowlist, PolicyViolation
from .types import ActionResult, ElementRef, InteractiveElement, LocatorStrategy


# ----------------Locator stability ----------------------

def is_stable_css(selector: str) -> bool:
    """An #id or [name=...] selector survives layout changes; a positional path doesn't."""
    return selector.startswith("#") or "[name=" in selector


# -------------- locator to live ele ---------------------

_ACCESSIBLE_NAME_JS = "el => (el.getAttribute('aria-label') || el.innerText || el.textContent || '').trim()"


def to_playwright_locator(page: Page, ref: ElementRef) -> Locator:
    if ref.strategy == LocatorStrategy.ROLE_NAME:
        return page.get_by_role(ref.role, name=ref.value, exact=False).first
    if ref.strategy == LocatorStrategy.CSS:
        return page.locator(ref.value).first
    if ref.strategy == LocatorStrategy.TEXT:
        return page.get_by_text(ref.value, exact=False).first
    if ref.strategy == LocatorStrategy.XPATH:
        return page.locator(f"xpath={ref.value}").first
    raise ValueError(f"Unknown strategy {ref.strategy}")


def name_matches(loc: Locator, candidate: ElementRef) -> bool:
    """
    Guards against a fallback locator landing on the wrong element
    checks links and buttons found by an unstable locator
    everything else should pass
    """
    if not candidate.expected_name:
        return True  # older artifacts have no name to check
    if candidate.strategy == LocatorStrategy.CSS and is_stable_css(candidate.value):
        return True
    if candidate.role not in ("link", "button"):
        return True
    try:
        actual = loc.evaluate(_ACCESSIBLE_NAME_JS)
    except Exception:
        return True
    if not actual:
        return True
    return candidate.expected_name.strip().lower() in actual.strip().lower()


def resolve_locator(page: Page, ref: ElementRef) -> Locator:
    """
    main locator => fallback in order
    
    Returns the first that becomes visible and passes the name check
    otherwise raise with every attempt
    """
    errors = []
    for candidate in [ref] + ref.fallbacks:
        try:
            loc = to_playwright_locator(page, candidate)
            loc.wait_for(state="visible", timeout=3000)
            if not name_matches(loc, candidate):
                errors.append(f"{candidate.strategy.value}='{candidate.value}': resolved but name mismatch")
                continue
            return loc
        except Exception as e:
            errors.append(f"{candidate.strategy.value}='{candidate.value}': {type(e).__name__}: {e}")
    raise RuntimeError(f"No locator strategy matched. Attempts: {' | '.join(errors)}")


# --------------  failures --------------

def diagnose_select_failure(loc: Locator, value: str) -> str:
    """Explains in plain words why a dropdown selection failed"""
    try:
        options = loc.locator("option")
        count = options.count()
        if not loc.is_visible():
            return "The dropdown isn't visible on the page right now."
        if count == 0:
            return "The dropdown is visible but has 0 options loaded — the page likely hadn't finished loading yet."
        values = [options.nth(i).get_attribute("value") for i in range(count)]
        if value in values:
            return f"'{value}' IS present among {values} — the failure was something else (timing, stale element, etc.)."
        return f"The dropdown has {count} option(s): {values}. '{value}' isn't one of them."
    except Exception as e:
        return f"Couldn't inspect the dropdown: {type(e).__name__}: {e}"


def select_failure_message(loc: Locator, value: str, error: Exception) -> str:
    first_line = str(error).splitlines()[0]
    return f"{diagnose_select_failure(loc, value)} | raw error: {type(error).__name__}: {first_line}"




# -------------- Nav guard --------------

def is_top_level_navigation(request: Request) -> bool:
    """
        True for a navigation of a whole tab + popups not an iframe
        TODO: iframes 
    """
    if not request.is_navigation_request():
        return False
    try:
        return request.frame.parent_frame is None
    except Exception:
        return True





# -------------- Building ActionResults --------------

def elapsed_ms(start: float) -> int:
    return int((time.time() - start) * 1000)


def succeeded(action: str, label: str, start: float, value: str | None = None) -> ActionResult:
    return ActionResult(True, action, label, duration_ms=elapsed_ms(start), value=value)


def failed(action: str, label: str, error) -> ActionResult:
    return ActionResult(False, action, label, error=str(error))


def refused(action: str, label: str, error) -> ActionResult:
    """A failure caused by the allowlist."""
    return ActionResult(False, action, label, error=str(error), policy_violation=True)


def policy_refusal(allowlist: Allowlist, action: str, url: str, label: str, reported_as: str | None = None) -> ActionResult | None:
    """
    Checks the allowlist before acting
    Returns a refused result, or None

    if the action may go ahead => reported_as overrides the action name in the result
    """
    try:
        allowlist.check_action(action, url=url)
    except PolicyViolation as e:
        return refused(reported_as or action, label, e)
    return None


# -------------- Perception --------------

ROLE_TO_ELEMENT_TYPE = {
    "button": "button", 
    "link": "link", 
    "textbox": "textbox",
    "checkbox": "checkbox", 
    "radio": "checkbox", 
    "combobox": "select",
}


def build_locator(role: str, name: str, css: str) -> ElementRef:
    """
    The main locator plus its fallback chain for one element

    A stable CSS selector goes first
    Otherwise role+name goes first and the positional CSS path is the last resort, since it breaks when the layout changes
    Text is only used as a fallback for links and buttons
    """
    role_ref = ElementRef(LocatorStrategy.ROLE_NAME, value=name, role=role, expected_name=name)
    css_ref = ElementRef(LocatorStrategy.CSS, value=css, role=role, expected_name=name)
    text_ref = (
        ElementRef(LocatorStrategy.TEXT, value=name, expected_name=name)
        if role in ("link", "button") else None
    )

    if is_stable_css(css):
        primary, chain = css_ref, [role_ref, text_ref]
    else:
        primary, chain = role_ref, [text_ref, css_ref]

    primary.fallbacks = [r for r in chain if r]
    return primary


def to_interactive_element(item: dict) -> InteractiveElement:
    """Turns one raw element from extract_elements.js into an InteractiveElement"""
    role, name, css = item["role"], item["name"], item["cssSelector"]
    return InteractiveElement(
        ref=build_locator(role, name, css),
        role=role,
        accessible_name=name,
        element_type=ROLE_TO_ELEMENT_TYPE.get(role, "other"),
        options=item.get("options", []),
    )


def trimmed_text(page: Page, max_chars: int = 2000) -> str:
    return page.inner_text("body")[:max_chars]