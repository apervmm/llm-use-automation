
from artifact.schema import Checkpoint
from surface.browser import BrowserSession


def checkpoint_met(session: BrowserSession, checkpoint: Checkpoint) -> bool:
    if checkpoint.kind == "url_contains":
        return checkpoint.expected in session.get_url()
    if checkpoint.kind == "text_visible":
        return checkpoint.expected in session.get_visible_text()
    if checkpoint.kind == "element_visible":
        return session.is_visible(checkpoint.expected)
    return False