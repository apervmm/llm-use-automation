import pytest

from actions import Action, ActionKind, execute
from artifact.schema import StepAction
from surface.types import ActionResult

REF = object()  


class FakeSession:
    def __init__(self, dialogs=None):
        self.calls = []
        self._dialogs = list(dialogs or [])

    def _ok(self, name, *args):
        self.calls.append((name, *args))
        return ActionResult(True, name, "fake", value="page text" if name == "read_text" else None)

    def goto(self, url):return self._ok("goto", url)
    def click(self, ref, description=""):return self._ok("click", ref)
    def type_text(self, ref, text, description=""):return self._ok("type_text", ref, text)
    def select_option(self, ref, value, description=""):return self._ok("select_option", ref, value)
    def read_text(self, ref, description=""):return self._ok("read_text", ref)

    def pop_dialogs(self):
        seen, self._dialogs = self._dialogs, []
        return seen


@pytest.mark.parametrize("action, expected_call", [
    (Action(ActionKind.NAVIGATE, value="http://x/a"), ("goto", "http://x/a")),
    (Action(ActionKind.CLICK, REF), ("click", REF)),
    (Action(ActionKind.TYPE_TEXT, REF, "john"),("type_text", REF, "john")),
    (Action(ActionKind.SELECT_OPTION, REF, "13344"),("select_option", REF, "13344")),
    (Action(ActionKind.READ, REF),("read_text", REF)),
])
def test_each_kind_calls_its_surface_method(action, expected_call):
    session = FakeSession()
    assert execute(session, action).success
    assert session.calls == [expected_call]


def test_a_missing_target_fails_without_touching_the_page():
    session = FakeSession()
    result = execute(session, Action(ActionKind.CLICK))
    assert not result.success and "target" in result.error
    assert session.calls == []


def test_a_missing_value_fails_without_touching_the_page():
    session = FakeSession()
    result = execute(session, Action(ActionKind.TYPE_TEXT, REF))
    assert not result.success and "value" in result.error
    assert session.calls == []


def test_a_dialog_turns_success_into_failure():
    result = execute(FakeSession(dialogs=["alert: Session expired"]), Action(ActionKind.CLICK, REF))
    assert not result.success and "Session expired" in result.error


def test_action_kinds_match_step_actions():
    assert {k.value for k in ActionKind} == {s.value for s in StepAction}