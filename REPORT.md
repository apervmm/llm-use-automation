

## 1. Architecture
Based on the assignment specification, the system has to have two distinct flows of the execution: non-deterministic llm `agent` to generate `artifact`, and deterministic `replay` mechanism to use this the same artifact for reproduction. The system is restructured into independent modular components that gets used as shown in diagram below.

<p align="center">
    <img width="960" height="900" alt="image" src="https://github.com/user-attachments/assets/3a25da69-b092-405a-bc26-be65aba16ace" />
</p>

- **Agent:** takes a goal and a starting URL. On each turn it takes a snapshot of the current page, sends that state plus the goal to the model, and asks for one next action from a fixed set: `click`, `type_text`, `navigate`, `read`, `select_option`, or declare the goal done. It executes that one action, records whether it succeeded, and feeds the result back in before asking for the next actio and repeats until:

1. the model reports the goal is done
2. the step limit (15) is reached — extendable by 3 more steps if a human resumes from escalation
3. 3 consecutive failed actions occur — also escalates to a human


- **Replay:** Takes a saved artifact — loaded by capability ID from the `/artifacts/` store — and a set of input values supplied by the caller at invocation time `--input` flag. It walks the artifact's steps in the recorded order, substituting each input into the step that expects it, and executes each step against the same kind of session the agent used. After the last step, it checks whether the artifact's declared condition for success actually holds on the page. 

- **Surface:** is the layer where both Agent and Replay act on — a single wrapper around one browser session that   neither of them bypasses, where their interactions on the actions are exectuted through actions methods `read_text`, `click`, `goto`, `select_option`, or `type_text`.
  It provides a `snapshot()` for agent that constructs a `pageState`, which consist of the `interactive elements`, `visible text` and a `screenshot` of the page to work on. 

    ```python
    @dataclass
    class PageState:
        url: str
        title: str
        interactive_elements: list[InteractiveElement]
        visible_text_summary: str
        screenshot_path: Optional[str] = None
    ```

- **CLI:** is an orchestrator layer that brings `surface`, `artifacts`, `agent`, and `replay` together.

**Key decisions and trade-offs:**

- **A fixed action set, via tool-calling, over free-text actions.**
  Every turn, the model must return one call from a closed set
  (`click`, `type_text`, `navigate`, `read`, `select_option`, `done`)
  rather than a free-form response. This makes actions reliably
  parseable and keeps the transcript close to the artifact schema's
  own shape, at the cost of flexibility like drag-and-drop, etc.
- **Surface as the one seam both Agent and Replay go through.**
  Neither component talks to Playwright or raw HTML directly — both
  act only through `Surface`'s methods and see only `PageState`/
  `ElementRef`. This is deliberate: it's the seam that would let a
  future desktop or legacy-app surface (Section 3.7) be swapped in by
  rewriting `surface/perception.py` alone, without touching the agent
  loop, artifact schema, or replay engine. The cost is that everything
  — every click, every read — is forced through this one interface,
  even where a more direct call might otherwise be simpler.
- **Single browser session, synchronous execution, over
  services/queues.** Agent, Replay, and escalation all run as one
  Python process against one live browser session at a time. This
  keeps the system simple — there is exactly one thing happening at
  once, so there's no coordination logic to write or reason about. The
  cost is that this doesn't scale to concurrent runs without real
  rework; running two capabilities at the same time isn't supported
  today.


## 2. Artifact schema

The main artifact is `Capability`, which is a versioned and typed schema that consists of 12 fields for 5 groups of reasons:

```python
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

- **Identity/Version Control:** is used specifically for versioning and grouping artifact schemas populated by discovery runs, it consist of the unique `capability_id`. The `version` auto-increments against existing files on disk. The `description` is populated automatically from the discovery goal, giving a human-readable summary. The `target_app` is currently fixed to `"parabank"` - to expand generacally for different apps. So the path for the versioned artifact would look like this: `<target_app>.<capability_id>.v<N>.json`

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
     - `name`: the key the caller sees in the result, e.g.
    `login_succeeded`.
    - `source_label`: which live `read` step this value comes from during
        replay, matched against that step's `read_label`.
    - `derived_from_outcome`: `true` means this value is set from whether
        replay succeeded or hit a business outcome, instead of being read
        from the page. This is partially redundant with `ReplayResult`'s
        own `status`/`outcome_name` fields, and I considered removing it (See 7.Cuts)
        but doing so makes fields like `loan_status` depend entirely on a
        live `read` of plain page text, and reading a value sitting *next
        to* a label (rather than inside a clickable element) isn't
        reliable yet (see Cuts). Kept deliberately for now, as a fallback
        that doesn't depend on a read path that can still silently return
        the wrong thing.
    - `description`: optional notes — not currently populated anywhere.

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
      - `target`: which element to act on using an `ElementRef`, which consists of a locator and
        fallback chain saved from what worked live during discovery. `None` for `navigate`, since            there's no element to find.
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
  1. A capability that depends on another (e.g. `parabank.request_loan` needs `parabank.login` first) doesn't embed the dependency's steps. 
  
  Instead, the capability's *recording config*, a separate YAML file, names an `auth_capability_id`, which the CLI replays first. This keeps each saved `Capability` single-purpose and independently replayable.




## 3. Determinism & error handling

#### Deterministic replay
Replay is deterministic because nothing is decided at runtime. There are three points where a decision could happen, and each one is fixed in advance: 
1. **Which actions to take.** Replay does not call the LLM. It runs `capability.steps` in `step_num` order with the recorded targets and values. The only thing that changes between runs is the `{param}` placeholders, which `_substitute()` fills from the caller's inputs. 
2. **Whether the inputs are valid.** `_validate_inputs()` rejects missing required inputs, and `_substitute()` rejects unknown parameters, before any UI action. A bad input stops the run before it starts, instead of partway through. 
3. **Whether the run succeeded.** This is decided by `checkpoint` and `outcome_rules` (text or URL checks), not by a model reading the page. 

The same inputs always produce the same actions. The result can still differ, because the application's data can differ. For example, the same `request_loan` steps can be approved or denied depending on the account balance. This is why the result types below separate a business outcome from a failure.

**Element Targeting** 
Fixed steps are only useful if each step finds the same element every time. A single locator can break when markup changes slightly, so each step stores a primary locator and fallbacks, all captured from the element used during discovery. The order depends on how stable the CSS selector is: 
1. **Stable selector** (`#id` or `[name=...]`):  CSS first, then role + name, then visible text. 
2. **Positional selector** (`nth-of-type` path): role + name first, then visible text, then the positional CSS.

However, there's an issue with `Fallbacks` that could match the wrong element. So I added `_resolve()` to handle this by checking each candidate in the following order:
1. Waiting to 3s for the element to be visible. 
2. For links and buttons found by a non-stable locator, check that the element's name matches `expected_name`. If not, try the next candidate. 
3. If all candidates fail, raise an error listing each strategy and why it failed.

This way replay either acts on the right element or stops with a clear error. 


#### Result types
Since the application's data can change the result, replay needs to tell the caller what kind of result it got. Every run ends in one of three states: 
1. **`SUCCESS`**: the checkpoint was met and outputs are returned. Example: loan approved. 
2. **`BUSINESS_OUTCOME`**: the app gave a known non-success answer. This is a valid result, not an error. Examples: `invalid_credentials`, `insufficient_funds`. 
3. **`FAILURE`**: something unexpected happened and replay stopped. Examples: element not found, page unreachable, or any other thing that causes the fail.

The `executor.py` picks the state by checking in this order, both when a step fails and after the last step:
1. Checkpoint met → `SUCCESS`. 
2. An `outcome_rule` matches → `BUSINESS_OUTCOME`. Rules are checked in order and the first match wins, so specific messages are listed first. 
3. Neither → escalate to an operator (Section 5). If still unresolved → `FAILURE`.

Checking outcome rules before declaring failure is what keeps "loan denied" from being reported as a crash. In `/evidence/`, replaying `request_loan` with `amount=100000, down_payment=1` returns `business_outcome` as `insufficient_funds`.

A `FAILURE` includes `failed_step`, `expected`, `observed`, and `error`, plus a screenshot if an escalation was raised. This is enough to see where the run stopped and why.

#### Runtime conditions
The result types above only work if each runtime problem is sent to the right one. Each condition is handled as follows: 
1. **Missing or unknown input:** rejected before any UI action. The caller gets an error.
2. **Slow render or redirect:** each locator waits up to 3s, and the checkpoint is polled every 250ms for up to 5s. Replay continues. 
3. **Primary locator not found:** the next fallback is tried, with the name check. Replay continues. 
4. **Known app message:** matched by `outcome_rules` → `BUSINESS_OUTCOME`. 
5. **Action outside the allowlist:** blocked before acting → `FAILURE`. 
6. **Entry page unreachable:** 15s timeout, checked before step 1 → `FAILURE` at step 0. 
7. **Step fails and no rule matches:** escalated. The operator fixes it in the live session, then the step is retried once. Otherwise → `FAILURE`. 
8. **Risky capability not confirmed:** the operator must confirm before step 1. If aborted → `FAILURE`. 

The first three are recovered automatically. The rest either return a known result or stop with a clear error.

#### Limits 
Some conditions are not handled automatically yet. They still don't pass silently: each one causes a failed step and goes to an operator. 
1. **Not automated:** dismissing unexpected dialogs, retrying failed page loads, detecting session timeouts. The fix is to declare known interstitials in the artifact with a recovery action, the same way `outcome_rules` declare known results. 
2. **UI drift:** fallbacks and name checks handle small changes, such as a new id or a moved button. Larger changes fail at a specific step instead of acting on the wrong element. 
3. **Plain-text reads:** reading a value next to a label can return the label instead (e.g. `"loan_status": "Status:"`). See Cuts.


## 4. Heterogeneity & multi-tenant
*how your design extends to legacy web and desktop surfaces, and to reuse across institutions running the same app (see 3.7).*



## 5. Escalation & handoff
*how you detect "stuck," how a human takes control of the live session, and how control is handed back.*



## 6. Safety
*your guardrail model and its limits.*



## 7. Cuts
*what you deliberately left out, and what you'd build next

1. **Output extraction falls back to a name-pattern heuristic instead of
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


2. **`derived_from_outcome` is a workaround I'd remove, but only after
fixing plain-text reads.** It duplicates information already on
`ReplayResult` (`status`/`outcome_name`), so on its own it looks like
dead weight. But testing its removal exposed why it's still there:
`loan_status` falls back to a live `read` step, and reading a value
that sits next to a label in plain page text (not inside a clickable
element) isn't generally solved — a `following-sibling`-style fix
works for this specific page's layout, but silently returns the wrong
text (the label, not the value) on markup it wasn't built for. The
right sequence is: make plain-text reads reliable first, confirm
`loan_status` reads correctly across cases, then remove the redundant
field — not the other way around.
