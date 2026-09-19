from artifact.schema import Capability, Step, StepAction, InputParam, OutputField, Checkpoint
from artifact import store
from surface.types import ElementRef, LocatorStrategy

cap = Capability(
    capability_id="parabank.login",
    description="Log into ParaBank with a username and password.",
    entry_url="https://parabank.parasoft.com/parabank/index.htm",
    inputs=[
        InputParam(name="username", example="john"),
        InputParam(name="password", example="demo"),
    ],
    outputs=[
        OutputField(name="login_succeeded", type="string", source_label="login_succeeded"),
    ],
    checkpoint=Checkpoint(kind="url_contains", expected="/overview.htm"),
    steps=[
        Step(step_num=1, action=StepAction.TYPE_TEXT, value="{username}",
             description="Type username into Username field",
             target=ElementRef(strategy=LocatorStrategy.CSS, value='input[name="username"]', role="textbox")),
        Step(step_num=2, action=StepAction.TYPE_TEXT, value="{password}",
             description="Type password into Password field",
             target=ElementRef(strategy=LocatorStrategy.CSS, value='input[name="password"]', role="textbox")),
        Step(step_num=3, action=StepAction.CLICK,
             description="Click Log In",
             target=ElementRef(strategy=LocatorStrategy.CSS, value='input[value="Log In"]', role="button")),
    ],
)

path = store.save(cap)
print("Saved to:", path)

loaded = store.load("parabank.login")
print("Round-trip OK:", loaded == cap)
print(loaded.model_dump_json(indent=2))