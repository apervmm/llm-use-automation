

## 1. Architecture
Based on the assignment specification, the system has to have two distinct flows of the execution: non-deterministic llm `agent` to generate `artifact`, and deterministic `replay` mechanism to use this the same artifact for reproduction. The system is restructured into independent modular components that gets used as shown in diagram below.

<p align="center">
    <img width="960" height="900" alt="image" src="https://github.com/user-attachments/assets/3a25da69-b092-405a-bc26-be65aba16ace" />
</p>

- **Agent (`src/agent/`):** takes a goal and a start URL. On each turn, it observes the page, sends the observation and the goal to the model, and asks for exactly one next action from a fixed set: `click`, `type_text`, `navigate`, `read`, `select_option`, or `done`. The observation is text: the URL, the page title, the interactive elements (role, name, and dropdown options), and the start of the visible page text. A screenshot of every step is saved as evidence but not sent to the model. The agent executes the action through the surface, records whether it succeeded, and feeds the result back before asking for the next action. The one exception is read: the model reports the value it sees in the page text, and the loop records it. If the model names the element the value came from, that element is saved as the step's target, so replay can read it from the page later. The run ends when:

    1. the model reports the goal is `done`.
    2. the step limit (15 by default) is reached — extendable by 3 more steps if a human resumes from escalation
    3. 3 consecutive failed actions occur — also escalates to a human
    4. The human aborts at an escalation, or the escalation budget (2 per run) is used up.
    5. The start page can't be reached before the model is called at all.


- **Replay (`src/replay/`):** is started with the same YAML config used for discovery `--config` and the caller's values `--inputs "amount=1000,down_payment=10,from_account_id=13344"`. It loads the latest saved version of the capability, or a pinned one with `--version`. Before anything touches the browser, it checks the inputs against the artifact: required names present, no unknown names, every `{placeholder}` filled, and numbers where numbers are declared. A risky capability then needs an operator's confirmation. It runs the steps in `step_num` order, filling each `{param}` from the inputs, through the same surface the agent used. After the last step, it checks the checkpoint, then the outcome rules, and returns `SUCCESS`, `BUSINESS_OUTCOME`, or `FAILURE` (see Section 3).

- **Recorder and store (`src/artifact/`):** turn a successful agent run into a Capability artifact (Section 2) and save it as a new version in /artifacts/.
  
- **Surface (`src/surface/`):** is `BrowserSession` together with `perception.py`: a wrapper around one Playwright browser session. Agent, Replay, and the escalation module act on the page only through it; nothing outside `src/surface/` calls Playwright directly. It provides:
  1. **Actions**: `click`, `type_text`, `select_option`, `read_text`, and `goto`. Each checks the allowlist first and returns an ActionResult.
  2. **Observation**: `perception.snapshot(session)` builds a PageState for the agent: the interactive elements (each with a locator and fallbacks), the visible text, and a screenshot.
  3. **Helpers** used by replay and escalation: `get_url`, `get_visible_text`, `wait`, `is_visible`, `screenshot`, `bring_to_front`, and `pop_dialogs`, which reports any JavaScript dialog that appeared and was dismissed.

    ```python
    @dataclass
    class PageState:
        url: str
        title: str
        interactive_elements: list[InteractiveElement]
        visible_text_summary: str
        screenshot_path: Optional[str] = None
    ```

- **Escalation (`src/escalation/`):** hands the live browser to a human operator when the agent is stuck, a replay step fails, or a risky capability needs confirmation, and records the operator's decision (see Section 5).

- **Safety (`src/safety/`):** the allowlist that every action is checked against, and redaction of sensitive values in artifacts and logs (see Section 6).
  
- **CLI (`src/cli.py`):** is the orchestrator, where
  1. `discover` runs the agent, checks the checkpoint, and records and saves the artifact.
  2. `replay` validates the inputs before opening the browser and then runs the replay from the artifact.
  Each run writes its evidence to its own folder under `/evidence/`.

**Key decisions and trade-offs:**
- **A fixed action set over free-text actions.** Every turn, the model must return one call from a closed set (`click`, `type_text`, `navigate`, `read`, `select_option`, `done`) rather than a free-form response. This makes actions reliably parseable and keeps the transcript close to the artifact schema's own shape, at the cost of flexibility like drag-and-drop, etc.
- **A text observation over screenshots.** The model chooses from a list of named interactive elements, and each of those already carries a locator and fallbacks. So whatever the model clicks can be recorded as a replayable step without any image understanding at replay time. The cost is that the model can't use purely visual information, such as an unlabeled icon or a canvas.
- **Surface as the one seam both Agent and Replay go through.** Neither component talks to Playwright or raw HTML directly — both act only through `Surface`'s methods and see only `PageState`/`ElementRef`. This is the seam that would let a future desktop or legacy-app surface (see Section 4) be swapped in by writing a new session class with the same methods and a matching `perception.py`, without touching the agent loop, artifact schema, or replay engine. The cost is that everything, every click and every read, is forced through this one interface, even where a more direct call would be simpler.


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

### Deterministic replay
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


### Result types
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

### Runtime conditions
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

### Limits 
Some conditions are not handled automatically yet. They still don't pass silently: each one causes a failed step and goes to an operator. 
1. **Not automated:** dismissing unexpected dialogs, retrying failed page loads, detecting session timeouts. The fix is to declare known interstitials in the artifact with a recovery action, the same way `outcome_rules` declare known results. 
2. **UI drift:** fallbacks and name checks handle small changes, such as a new id or a moved button. Larger changes fail at a specific step instead of acting on the wrong element. 
3. **Plain-text reads:** reading a value next to a label can return the label instead (e.g. `"loan_status": "Status:"`). See Cuts.


## 4. Heterogeneity & multi-tenant

The system is built against one surface (ParaBank in a browser) and one
tenant. Multi-surface and multi-tenant support are not implemented, but
the core abstractions were designed so that adding them extends the
system rather than replacing parts of it.

### The seam between surface and flow
To support other surfaces, the recorded flow must not depend on how a
surface is driven. The current design splits the system into two parts:

1. **The flow** (the artifact): `steps`, `inputs`, `outputs`,
   `checkpoint`, and `outcome_rules`. It describes *what* to do: "type
   `{username}` into the Username textbox, click Log In, expect
   `/overview.htm`."
2. **The surface** (`BrowserSession` and `perception.py`): turns each
   step into a real action. It handles *how*: finding elements, clicking,
   typing, reading text, taking screenshots.

Agent and Replay call the surface through five actions (`click`,
`type_text`, `select_option`, `read_text`, `goto`) plus `snapshot()`.
Each returns an `ActionResult`. A new surface would only need to
implement these methods. The artifact schema, replay order, and result
types would stay the same.

The one surface-specific part of the artifact is the locator.
`ElementRef` stores the kind of locator separately from its value, so
each surface can use its own kinds without changing the schema.

### Legacy web apps
Legacy web apps use the same surface, but their markup is harder to
target. The current design handles some of these cases but not all:

1. **No ids or test IDs:** already handled. The CSS locator falls back
   from id to `name` attribute to a positional path, with `role_name`
   and `text` as fallbacks. ParaBank's Log In button has no id or name,
   so it uses a positional path, which is more brittle to layout changes.
2. **Framesets and iframes:** not handled yet. `_to_playwright_locator()`
   searches only the main page. The fix is to add a frame path to
   `ElementRef`, so the locator is resolved inside the right frame.
3. **Elements with no accessible name:** some legacy controls have no
   label, and `perception.py` already falls back to nearby text. A
   screenshot + coordinates strategy could be added as one more
   `LocatorStrategy`.

### Desktop apps
A desktop app needs a new surface class, not a new artifact:

1. **`DesktopSession`** implements the same five actions using an OS
   accessibility API (e.g. UI Automation on Windows).
2. **`snapshot()`** reads the accessibility tree instead of the DOM and
   returns the same `PageState`: interactive elements, visible text,
   screenshot.
3. **Locators** use `role_name` (an accessible role and name, e.g.
   `button` / "Log In"). It comes from the accessibility tree, which
   exists on both web pages and desktop apps (Windows UI Automation,
   macOS Accessibility). This is why `role_name` is kept in the fallback
   chain on the web: it is the strategy that carries over to desktop,
   where it becomes the primary locator. CSS and XPath are not generated
   for desktop steps.
4. **`checkpoint` and `outcome_rules`** use `text_visible` as they do
   now. `url_contains` would need a desktop equivalent, such as the
   window title.

Screenshot + coordinates is possible as a final fallback for controls
with no accessibility data, but it would be the least stable option. A
step that can only be found by coordinates should escalate to a human
rather than click blindly.

### Multi-tenant reuse
Many tenants run the same vendor product with different branding, URLs,
and settings. Recording the same flow for each tenant would repeat most
of the work. Instead, the current artifact becomes a shared base, and
each tenant can add a small override file:

1. **Base artifact:** recorded once per vendor product, e.g.
   `<vendorX>.<capability>.v<N>`. It holds the steps, locators, inputs,
   outputs, and rules that are the same for every tenant.
2. **Tenant override:** a small file per tenant that changes only what
   differs, such as the base URL, a relabeled button name, or a
   different error message in `outcome_rules`. An override cannot add or
   remove steps; a tenant with a different flow gets its own artifact.

At replay time, the override is merged onto the base artifact. A tenant
with no differences needs no override. A base artifact is not trusted on
a new tenant until a test replay passes; if it fails, the tenant gets an
override or a new discovery run instead of a silently broken capability.

Part of this already exists: the base URL comes from
`PARABANK_BASE_URL`, so the same capability config runs against
localhost or the public demo. The saved artifact still stores the full
`entry_url`, so the next step is to store a relative path and resolve
the host per tenant.

### Detecting drift
Tenants upgrade vendor versions at different times, so an artifact that
works for one tenant can break for another. Drift shows up in replay
results:

1. **Fallback used:** the primary locator failed, but a fallback worked.
   This is an early sign of a markup change. Replay would log which
   candidate was used.
2. **Step failure at the same step across runs** for one tenant, while
   other tenants pass. This points to a tenant-specific change, not a
   general one.
3. **New unmatched messages:** the checkpoint fails and no
   `outcome_rule` matches. This often means the app shows a message the
   artifact doesn't know about.

When drift is detected, discovery is re-run for that tenant. The
differences are saved as a tenant override, or as a new base version if
many tenants are affected. Tenants that have not upgraded keep using the
previous version.

### Limits
This section is mostly design. What is built and what is not:

1. **Built:** the surface/flow split, `ElementRef` with a locator kind
   and fallback chain (CSS primary, `role_name` and `text` fallbacks),
   the shared `ActionResult` and `PageState` types, and base-URL
   switching through an environment variable.
2. **Not built:** a surface interface class, desktop or iframe support,
   tenant overrides, test replays for new tenants, and drift logging.
3. **Known leak:** `_check_outcomes()` and the `element_visible`
   checkpoint call `session.page` directly. These are Playwright calls
   outside the surface and would need to move into `BrowserSession`
   before a second surface could be added.


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
