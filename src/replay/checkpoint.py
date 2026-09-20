
from artifact.schema import Checkpoint
from surface.browser import BrowserSession


def checkpoint_met(session: BrowserSession, checkpoint: Checkpoint) -> bool:
    if checkpoint.kind == "url_contains":
        return checkpoint.expected in session.page.url
    if checkpoint.kind == "text_visible":
        return checkpoint.expected in session.page.inner_text("body")
    if checkpoint.kind == "element_visible":
        return session.page.locator(checkpoint.expected).first.is_visible()
    return False