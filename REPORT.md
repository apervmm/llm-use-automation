

## 1. Architecture
Based on the assignment specification, the system has to have two distinct flows of the execution: non-deterministic llm `agent` to generate `artifact`, and deterministic `replay` mechanism to use this the same artifact for reproduction. The system is restructured into independent modular components that gets used as shown in diagram below.

<p align="center">
    <img width="960" height="900" alt="image" src="https://github.com/user-attachments/assets/3a25da69-b092-405a-bc26-be65aba16ace" />
</p>

- **Agent:** takes a goal and a starting URL. On each turn it takes a snapshot of the current page, sends that state plus the goal to the model, and asks for one next action from a fixed set: `click`, `type_text`, `navigate`, `read`, `select_option`, or declare the goal done. It executes that one action, records whether it succeeded, and feeds the result back in before asking for the next actio and repeats until:
```
1. the model reports the goal is done
2. the step limit (15) is reached — extendable by 3 more steps if a human resumes from escalation
3. 3 consecutive failed actions occur — also escalates to a human
```

- **Replay:** Takes a saved artifact — loaded by capability ID from the `/artifacts/` store — and a set of input values supplied by the caller at invocation time `--input` flag. It walks the artifact's steps in the recorded order, substituting each input into the step that expects it, and executes each step against the same kind of session the agent used. After the last step, it checks whether the artifact's declared condition for success actually holds on the page. 

- **Surface:** is the layer where both Agent and Replay act on — a single wrapper around one browser session that neither of them bypasses, where their interactions on the actions are exectuted through actions methods `read_text`, `click`, `goto`, `select_option`, or `type_text`.

It provides a `snapshot()` for agent that constructs a `pageState`, which consist of the `interactive elements`, `visible text` and a `screenshot` of the page to work on. 

```
@dataclass
class PageState:
    url: str
    title: str
    interactive_elements: list[InteractiveElement]
    visible_text_summary: str
    screenshot_path: Optional[str] = None
```

- **CLI:** is an orchestrator layer that brings `surface`, `artifacts`, `agent`, and `replay` together.



## 2. Artifact schema

The main artifact is `Capability`, which is a versioned and typed schema that consists of 12 fields for 5 groups of reasons:

```
class Capability(BaseModel):
    # Identity/Version Control
    capability_id: str                     
    version: int = 1
    description: str = ""
    target_app: str = "parabank"

    # Entry Point
    entry_url: str

    # Behavioral Contract
    inputs: list[InputParam] = Field(default_factory=list)
    outputs: list[OutputField] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    checkpoint: Optional[Checkpoint] = None
    outcome_rules: list[OutcomeRule] = Field(default_factory=list)

    # Metadata
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    # Safety Classifier
    risk_level: RiskLevel = RiskLevel.SAFE
```

- **Identity/Version Control:** is used specifically for versioning and grouping artifact schemas populated by discovery runs, it consist of the unique `capability_id`. The `version` is not set by hand — `store.save()` auto-increments it against existing files on disk. The `description` is populated automatically from the discovery goal, giving a human-readable summary. The `target_app` is currently fixed to `"parabank"` — it isn't wired into any logic yet, since this project targets one app, but it's the natural field multi-tenant reuse for different products. So the path for the versioned artifact would look like this: `<target_app>.<capability_id>.v<N>.json`

- **Entry Point:** `entry_url` is where replay begins — the browser navigates here before the first step executes. Kept separate from `steps[]` because it isn't an action so much as a precondition for step 1 to make sense.

- **Behavioral Contract:** is a tracable actions of discovery runs that consists of `inputs`, `outputs`, `steps`, `checkpoint`, and `outcome_rules`, where they together define what actually happens when a capability runs and how its result is judged.
  - `inputs`: values supplied at replay time (e.g. `username`, `password`). Kept explicit rather than inferred, so a human decides what's parameterized — and sensitive examples (password/pin/ssn) are redacted before saving.
    ```
    class InputParam(BaseModel):
        name: str                         
        description: str = ""
        required: bool = True
        example: Optional[str] = None
    ```
  - `outputs`: the actual data a capability hands back (confirmation message, success status). How a value is produced differs by when it happens. During discovery, the agent self-reports these values itself when it finishes. During replay, values come from `_extract_outputs()` instead, using each field below.
    ```
    class OutputField(BaseModel):
        name: str                         
        description: str = ""
        source_label: str = ""    
        derived_from_outcome: bool = False   
    ```
    - `source_label`: which live `read` step this value should come from
    during replay, matched against that step's `read_label`. If no
    read step matches, the value falls back to a name-pattern guess
    (see Section 7, Cuts) or `None`.
  - `steps`: the ordered actions to replay.
    ```
    class StepAction(str, Enum):
        CLICK = "click"
        TYPE_TEXT = "type_text"
        NAVIGATE = "navigate"
        READ = "read"
        SELECT_OPTION = "select_option"
    
    class Step(BaseModel):
        step_num: int
        action: StepAction
        target: Optional[ElementRef] = None 
        value: Optional[str] = None   
        read_label: Optional[str] = None 
        description: str = ""
    ```
      - `step_num`: the step's position in the sequence — replay runs
    steps in this order, not the order they appear in the file.
      - `action`: which of the five actions to perform.
      - `target`: which element to act on — an `ElementRef` (locator +
        fallback chain) saved from what worked live during discovery.
        `None` for `navigate`, since there's no element to find.
      - `value`: the text to type, or the option to select. Holds either a
        literal or a `{param}` placeholder, depending on whether it was
        parameterized when recorded.
      - `read_label`: a human-readable name for what a `read` step
        captured (e.g. "confirmation message"). Currently just a label for
        logging/description purposes — despite the code comment, it isn't
        actually linked to an `OutputField` in the codebase yet.
      - `description`: a plain-English summary of the step like "click" or "login", generated automatically for readability when someone inspects the saved artifact.
  - `checkpoint`: the single condition that defines success, where `kind` is what to inspect and `expected` is what value to expect.
    ```
    class Checkpoint(BaseModel):
        kind: Literal["url_contains", "element_visible", "text_visible"]
        expected: str      
    ```
  - `outcome_rule`: named, expected non-success results. Checked only if the checkpoint fails — this keeps a normal negative answer separate from an actual error.
    ```
    class OutcomeRule(BaseModel):
        name: str   
        kind: Literal["text_visible", "url_contains"]
        expected: str
        description: str = ""   
    ```

- **Metadata:** `created_at` is a plain recording timestamp, useful for reading evidence logs and telling artifact versions apart chronologically.

- **Safety Classifier:** `risk_level` is computed automatically at record time from `allowlist.yaml`'s risky-capability patterns rather than set by hand, so a capability can't silently be recorded as `safe` by omission. It gates whether `replay()` requires `confirmed=True`.

<!-- <p align="center">
    <img width="529" height="551" alt="image" src="https://github.com/user-attachments/assets/f6fb6c15-b250-49b0-8846-5eb83b37cc40" />
    <br>
    <em>Conceptual data model — actual storage is one nested JSON file
    per capability version (see store.py), not a relational database.
    This diagram shows entity relationships only.</em>
</p> -->


- **Additional Features**
  1. A capability that depends on another (e.g. `parabank.request_loan` needs `parabank.login` first) doesn't embed the dependency's steps. Instead, the capability's *recording config* (a separate YAML, not the artifact itself) names an `auth_capability_id`, which the CLI replays first. This keeps each saved `Capability` single-purpose and independently replayable, at the cost of that dependency being declared outside the artifact schema.




## 3. Determinism & error handling
*how you make replay deterministic, and how you detect and handle runtime errors and exceptional states (and, secondarily, any UI drift).*



## 4. Heterogeneity & multi-tenant
*how your design extends to legacy web and desktop surfaces, and to reuse across institutions running the same app (see 3.7).*



## 5. Escalation & handoff
*how you detect "stuck," how a human takes control of the live session, and how control is handed back.*



## 6. Safety
*your guardrail model and its limits.*



## 7. Cuts
*what you deliberately left out, and what you'd build next

**Output extraction falls back to a name-pattern heuristic instead of
an explicit rule.** In `_extract_outputs()`, if an output isn't
`derived_from_outcome` and wasn't captured by a live `read` step, the
system guesses its value by checking whether the field's name contains
"succeed" or "success" (defaulting to `"true"` if so, `None`
otherwise). This works for the two capabilities in this project only
because their output names happen to match that pattern
(`login_succeeded`). It's fragile by construction: renaming that field
to `logged_in`, or adding an output like `account_verified`, would
silently return `None` instead of failing loudly — a naming
coincidence is doing the job a real declaration should. The correct
fix is to make the source explicit in the capability config rather
than inferred from a string match, e.g.:

    outputs:
      login_succeeded: { from: status }   # true on SUCCESS, false otherwise
      message: { from_read: message }     # pulled from a read step's value

This was cut because both current capabilities work under the
existing heuristic and building a small declarative mini-language for
output sourcing wasn't worth the time against two capabilities — but
it's the first thing I'd fix before adding a third.*
