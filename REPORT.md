

## 1. Architecture
Based on the assignment specification, the system has to have two distinct flows of the execution: non-deterministic llm `agent` to generate `artifact`, and deterministic `replay` mechanism to use this the same artifact for reproduction. The system is restructured into independent modular components that gets used as shown in diagram below.

<p align="center">
    <img width="960" height="900" alt="image" src="https://github.com/user-attachments/assets/3a25da69-b092-405a-bc26-be65aba16ace" />
</p>

- **Agent (`src/agent/`):** takes a goal and a start URL. On each turn, it observes the page, sends the observation and the goal to the model, and asks for exactly one next action from a fixed set: `click`, `type_text`, `navigate`, `read`, `select_option`, or `done`. The observation is text: the URL, the page title, the interactive elements (role, name, and dropdown options), and the start of the visible page text. A screenshot of every step is saved as evidence but not sent to the model. The agent executes the action through the surface, records whether it succeeded, and feeds the result back before asking for the next action. The one exception is read: the model reports the value it sees in the page text, and the loop records it. If the model names the element the value came from, that element is saved as the step's target, so replay can read it from the page later. The run ends when:

    1. the model reports the goal is `done`.
    2. the step limit (15 by default) is reached. This escalates to a human; if they resume, the agent gets 3 more steps.
    3. 3 actions fail in a row. This also escalates to a human.
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
- **A config file per capability.** Each capability starts from a short YAML file written by a person (`capabilities/login.yaml`, `capabilities/loan.yaml`): the goal, the start page, which values become inputs, how success is checked, and which answers count as normal results. The agent only works out the steps. This keeps the decisions that make replay trustworthy out of the LLM's hands, and a file is easier to review, change, and reuse than a long command with a paragraph-long goal. The cost is writing a config for each new capability. 


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

- **Identity/Version Control:** is used specifically for versioning and grouping artifact schemas populated by discovery runs; it consists of the unique `capability_id`. The `version` auto-increments against existing files on disk. The `description` is populated automatically from the discovery goal, giving a human-readable summary. The `target_app` is currently fixed to `"parabank"` - to expand generically for different apps. So the path for the versioned artifact would look like this: `<target_app>.<capability_id>.v<N>.json.`

- **Entry Point:** `entry_url` is where replay begins — the browser navigates here before the first step executes. Kept separate from `steps[]` because it isn't an action so much as a precondition for step 1 to make sense.

- **Behavioral Contract:** is a traceable set of actions of discovery runs that consists of `inputs`, `outputs`, `steps`, `checkpoint`, and `outcome_rules`, where they together define what actually happens when a capability runs and how its result is judged.
  - `inputs`: values supplied at replay time like `username` or `amount`. They are declared explicitly in the discovery config rather than inferred, so a human decides what's parameterized.
    ```
    class InputParam(BaseModel):
        name: str
        type: ParamType = ParamType.STRING                  
        description: str = ""
        required: bool = True
        example: Optional[str] = None
    ```
    - `name`: the placeholder used in step values (`{amount}`) and the key the caller passes in `--inputs`.
    - `type`: inferred at record time from the value the agent actually used (`1000` -> `number`, `demo` -> `string`) and enforced before replay starts, so `amount=abc` is rejected at step 0.
    - `description`: optional notes, not currently populated.
    - `required`: whether replay rejects a run that doesn't supply this input. Every recorded input is currently required.
    - `example`: the value used during discovery, so a reader can see what a valid input looks like. Sensitive examples (`password`, `pin`, `ssn`) are saved as `[REDACTED]`.
    
    Recording also fails if a declared parameter never matched a typed or selected value, so a credential can't end up stored as a literal step value (Section 6).

  - `outputs`: he data a capability hands back (e.g. `login_succeeded`, `loan_status`, `new_account_id`). During discovery, the agent reports these values itself when it finishes. During replay, `_extract_outputs()` produces them from the fields below.
    ```
    class OutputField(BaseModel):
        name: str
        type: ParamType = ParamType.STRING                  
        description: str = ""
        source_label: str = ""    
        derived_from_outcome: bool = False   
    ```
    - `name`: the key the caller sees in the result, e.g., `new_account_id`.
    - `type`: always `string` for now, because every output value is read from page text.
    - `description`: optional notes, not currently populated.
    - `source_label`: which `read` step's value this output takes during replay, matched against that step's `read_label`.
    - `derived_from_outcome`: `true` means the value comes from how replay ended rather than from the page: `"success"` on `SUCCESS`, the matched outcome rule's name on `BUSINESS_OUTCOME` (e.g. `insufficient_funds`), and `null` on `FAILURE`. `loan_status` uses this. It partly duplicates `ReplayResult.status` / `outcome_name`; it is kept because reading a status that sits next to a label in plain page text isn't reliable yet (see Cuts).

  - `step`: the ordered actions to replay.
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
      - `target`: the element to act on, as an `ElementRef`: a primary locator plus a fallback chain, all captured from the element used during discovery (Section 3). `None` for `navigate`, and for a `read` whose value didn't come from a specific element.
        ```
        @dataclass
        class ElementRef:
              strategy: LocatorStrategy          # css | role_name | text | xpath
              value: str
              role: Optional[str] = None
              expected_name: Optional[str] = None
              fallbacks: list["ElementRef"] = field(default_factory=list)
        ```
      - `value`: the text to type, or the option to select. Holds either a literal or a `{param}` placeholder, depending on whether it was parameterized when recorded.
      - `read_label`: for `read` steps, the name the value is stored under. At the end of replay, each output looks up its `source_label` among these names, which is how `new_account_id` is returned. A `read` step with no target is skipped at replay.
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


**Additional Features**
  1. A capability that depends on another (e.g., `parabank.request_loan` needs `parabank.login` first) doesn't embed the dependency's steps. Instead, its discovery config names an `auth_capability_id`, which the CLI replays first. This keeps each saved `Capability` single-purpose and independently replayable.




## 3. Determinism & error handling

### Deterministic replay
Replay is deterministic because nothing is decided at runtime. There are three points where a decision could happen, and each one is fixed in advance: 
1. **Which actions to take.** Replay does not call the LLM. It runs `capability.steps` in `step_num` order with the recorded targets and values. The only thing that changes between runs is the `{param}` placeholders, which `_substitute()` fills from the caller's inputs. 
2. **Whether the inputs are valid.** `input_errors()` checks the caller's inputs against the artifact before anything else: missing required inputs, unknown input names (e.g., a typo like `amout`), `{placeholders} `with no value, and values that aren't numbers where the artifact declares `number`. Any problem returns `FAILURE` at step 0, listing every problem, e.g., `Invalid inputs: missing required input(s): ['amount']; unknown input(s): ['amout']`. The CLI runs the same check before it opens the browser, so a bad input never reaches the login or the risky-confirmation prompt.
3. **Whether the run succeeded.** This is decided by `checkpoint` and `outcome_rules` (text or URL checks), not by a model reading the page. 

The same inputs always produce the same actions. The result can still differ, because the application's data can differ. For example, the same `request_loan` steps can be approved or denied depending on the account balance. This is why the result types below separate a business outcome from a failure.

### Element Targeting
Fixed steps are only useful if each step finds the same element every time. A single locator can break when markup changes slightly, so each step stores a primary locator and fallbacks, all captured from the element used during discovery. The order depends on how stable the CSS selector is: 
1. **Stable selector** (`#id` or `[name=...]`):  CSS first, then role + name, then visible text. 
2. **Positional selector** (`nth-of-type` path): role + name first, then visible text, then the positional CSS.

However, there's an issue with `Fallbacks` that could match the wrong element. So I added `_resolve()` to handle this by checking each candidate in the following order:
1. Wait up to 3s for the element to be visible. 
2. For links and buttons found by a non-stable locator, check that the element's name matches `expected_name`. If not, try the next candidate. 
3. If all candidates fail, raise an error listing each strategy and why it failed.
This way replay either acts on the right element or stops with a clear error. 


### Result types
Since the application's data can change the result, replay needs to tell the caller what kind of result it got. Every run ends in one of three states: 
1. **`SUCCESS`**: the checkpoint was met, and outputs are returned. Example: loan approved. 
2. **`BUSINESS_OUTCOME`**: the app gave a known non-success answer. This is a valid result, not an error. Examples: `invalid_credentials`, `insufficient_funds`. 
3. **`FAILURE`**: something unexpected happened and replay stopped. Examples: element not found, page unreachable, or policy violation

The `executor.py` picks the state by checking in this order, both when a step fails and after the last step:
executor.py picks the state as follows.

**When a step fails:**

1. A policy violation -> `FAILURE` immediately, with no escalation, so an operator can't retry a blocked action.
2. An `outcome_rule` matches the page -> `BUSINESS_OUTCOME`. Rules are checked in order and the first match wins, so specific messages are listed first.
3. Neither -> escalate to an operator (see Section 5). On `resume`, the step is retried once; if it still fails -> `FAILURE`.

**After the last step:**

1. Checkpoint met (polled for up to 5s) > `SUCCESS`.
2. An `outcome_rule` matches -> `BUSINESS_OUTCOME`.
3. Neither -> `escalate`; on `resume,` the checkpoint is checked again, otherwise -> `FAILURE`.

Checking outcome rules before declaring failure is what keeps "loan denied" from being reported as a crash. In `/evidence/`, replaying `request_loan` with `amount=100000, down_payment=1` returns `business_outcome` as `insufficient_funds`.

A `FAILURE` includes `failed_step`, `expected`, `observed`, and `error`, plus a screenshot if an escalation was raised. This is enough to see where the run stopped and why.


### Runtime conditions
The result types above only work if each runtime problem is sent to the right one. Each condition is handled as follows: 
1. **Missing or Invalid input:** rejected before any UI action -> `FAILURE` at step 0
2. **Slow render or redirect:** each locator waits up to 3s, and the checkpoint is polled every 250ms for up to 5s. Replay continues. 
3. **Primary locator not found:** the next fallback is tried, with the name check. Replay continues. 
4. **Known app message:** matched by `outcome_rules` -> `BUSINESS_OUTCOME`. 
5. **Action outside the allowlist:** every action checks the current URL against the allowlist first, and a top-level navigation to a route outside it, in the main tab or a popup, is cancelled before the page loads, so the browser stays where it was (see Limits for redirects).-> `FAILURE`, with no escalation, e.g. `Policy violation at step 3: Route '/parabank/overview.htm' is not in the allowed routes`.
6. **Entry page unreachable:** a 15s timeout, checked before step 1 -> `FAILURE` at step 0. 
7. **Unexpected JavaScript dialog (`alert`, `confirm`, `prompt`):** dismissed, never accepted, and the step that caused it fails with the dialog's text, e.g. `Unexpected dialog(s) dismissed: ['confirm: Really log in?']`. It then goes through outcome rules and escalation like any failed step.
8. **Step fails, and no rule matches:** escalated. The operator fixes it in the live session, then the step is retried once, with the same dialog and policy checks as the first attempt; dialogs raised while the operator was in control are discarded first. If the retry fails -> `FAILURE`.
9. **Risky capability not confirmed:** after the inputs are validated and before step 1, the operator must confirm. If aborted -> `FAILURE`. 

The first three are recovered automatically. The rest either return a known result or stop with a clear error.

### Limits 
Some conditions are not handled automatically yet. They still don't pass silently: each one causes a failed step and goes to an operator. 
1. **Not automated:** dismissing unexpected dialogs, retrying failed page loads, detecting session timeouts. The fix is to declare known interstitials in the artifact with a recovery action, the same way `outcome_rules` declare known results.
2. **Redirects:** the navigation guard cancels navigations the browser starts itself, such as clicking a link or opening a popup. A server redirect happens inside the response, so it is only caught after the page has loaded; replay still stops with FAILURE. The login is an example: the form posts to `login.htm`, which redirects to `overview.htm`.
3. **UI drift:** fallbacks and name checks handle small changes, such as a new id or a moved button. Larger changes fail at a specific step instead of acting on the wrong element. The name check is a "contains" match, so a button renamed from `Log In `to `Log In Now` would still pass.
4. **Plain-text reads:** reading a value next to a label can return the label instead (e.g. `"loan_status": "Status:"`). See Cuts.


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

Agent, Replay, and escalation reach the application only through the surface; nothing outside `src/surface/` calls Playwright. A new surface would implement the same methods as `BrowserSession`:
1. **Actions** returning an `ActionResult`: `click`, `type_text`, `select_option`, `read_text`, `goto`.
2. **Observation**: `snapshot()` returning a `PageState`.
3. **Helpers**: `get_url`, `get_visible_text`, `wait`, `is_visible`, `screenshot`, `bring_to_front`, `pop_dialogs`.

The artifact schema, replay order, and result types would stay the same. There is no formal interface class yet; BrowserSession is the de facto definition (see Limits).

The one surface-specific part of the artifact is the locator. `ElementRef` stores the kind of locator separately from its value, so each surface can use its own kinds without changing the schema.

### Legacy web apps
Legacy web apps use the same surface, but their markup is harder to target. The current design handles some of these cases but not all:
1. **No ids or test IDs:** already handled. The CSS locator falls back from id to `name` attribute to a positional path, with `role_name` and `text` as fallbacks. ParaBank's Log In button has no id or name, so it uses a positional path, which is more brittle to layout changes.
2. **Framesets and iframes:** not handled yet. `_to_playwright_locator()` searches only the main page. The fix is to add a frame path to `ElementRef`, so the locator is resolved inside the right frame.
3. **Elements with no accessible name:** some legacy controls have no label. The element extraction script (`surface/scripts/extract_elements.js`, `nearbyText()`) already falls back to text next to the control, such as the table-cell label `Loan Amount: $`. A screenshot + coordinates strategy could be added as one more `LocatorStrategy`.

### Desktop apps
A desktop app needs a new surface class, not a new artifact:
1. **`DesktopSession`** implements the same five actions using an OS accessibility API (e.g. UI Automation on Windows), with `pop_dialogs` reporting unexpected modal windows.
2. **`snapshot()`** reads the accessibility tree instead of the DOM and returns the same `PageState`: interactive elements, visible text, screenshot.
3. **Locators** use `role_name` (an accessible role and name, e.g.
   `button` / "Log In"). It comes from the accessibility tree, which
   exists on both web pages and desktop apps (Windows UI Automation,
   macOS Accessibility). This is why `role_name` is kept in the fallback
   chain on the web: it is the strategy that carries over to desktop,
   where it becomes the primary locator. CSS and XPath are not generated
   for desktop steps.
4. **`checkpoint` and `outcome_rules`** use `text_visible` as they do now. `url_contains` would need a desktop equivalent, such as the window title.
5. **Policy**: the allowlist is URL-based (domains and routes). A desktop surface needs its own policy keys, such as permitted applications and windows.

Screenshot + coordinates is possible as a final fallback for controls with no accessibility data, but it would be the least stable option. A step that can only be found by coordinates should escalate to a human rather than click blindly.


### Multi-tenant reuse
Many tenants run the same vendor product with different branding, URLs,
and settings. Recording the same flow for each tenant would repeat most
of the work. Instead, the current artifact becomes a shared base, and
each tenant can add a small override file:

1. **Base artifact:** recorded once per vendor product, e.g. `<vendorX>.<capability>.v<N>`. It holds the steps, locators, inputs, outputs, and rules that are the same for every tenant. This is the naming the store already uses: `target_app` is the id's prefix, applied in one place by `store.qualify()`.
2. **Tenant override:** a small file per tenant that changes only what differs, such as the base URL, a relabeled button name, or a different error message in `outcome_rules`. An override cannot add or remove steps; a tenant with a different flow gets its own artifact.

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

1. **Built:** the surface/flow split, `ElementRef` with a locator kind and fallback chain, the shared `ActionResult` and `PageState` types, and base-URL switching through an environment variable.
2. **Not built:** a surface interface class, desktop or iframe support, tenant overrides, test replays for new tenants, and drift logging.
3. **Still web-specific**: the `css` and `xpath` locator strategies, `url_contains` checkpoints and outcome rules, and the URL-based allowlist and navigation guard. A desktop surface needs an equivalent for each (see Desktop apps).


## 5. Escalation & handoff
All escalations use one mechanism: automation pauses, a human takes over the same live browser session the automation was using, and then hands control back with a decision.

### Detecting when to escalate
1. `dicovery_stuck`: triggered when the step limit is reached, 3 actions fail in a row, or the model returns no action.
2. `replay_failure`: triggered when the step fails and no `outcome_rule` matches the page, or the checkpoint isn't met and no `outcome_rule` matches
3. `risky_confirmation`: triggered before step 1 of any capability classified as risky (see Section 6)

Some conditions deliberately don't escalate, because a human can't or shouldn't fix them mid-run: invalid inputs and an unreachable entry page stop at step 0, and a policy violation stops the run immediately (see Section 3).

### Routing the request
`raise_escalation()` builds an `EscalationRequest` with the context an operator needs to act, and saves a screenshot of the current page into the run's evidence folder:
```
@dataclass
class EscalationRequest:
    reason: EscalationReason        
    capability_or_goal: str         
    current_step: int | None
    current_url: str
    detail: str                    
    screenshot_path: str | None
    timestamp: str
    run_id: str | None
```   
The operator sees the reason, task, step, URL, and detail in the terminal. For a failed step, the detail is the step's own error. For a risky confirmation, it lists the parameters about to be submitted and, when the page shows it, the current state of the account involved.


### Taking control
Discovery and replay always run in a visible browser window. When an escalation is raised:
1. The browser window is brought to the front. It is the same session, with the same login, cookies, and page, so the operator continues exactly where automation stopped.
2. `HandoffState.automation_in_control` is set to False, recording that the human is in control.
3. Automation blocks on the operator prompt. Because execution is synchronous (Section 1), no automated action can happen while the human is working in the browser.

### Handing control back
The operator types `resume` or `abort`, and can add a note describing what they did. 

- On `resume`, control returns to automation (`automation_in_control = True`), and what happens next depends on the reason:
    1. `discovery_stuck`: The agent observes the page again, so it sees whatever the human changed; its failure count is reset, and if the step limit was hit, it gets 3 more steps. At most 2 escalations per run.
    2. `replay_failure` (step): The failed step is retried once, with the same dialog and policy checks as the first attempt. Dialogs raised while the operator was in control are discarded first. If the retry fails -> `FAILURE`.
    3. `replay_failure` (checkpoint): The checkpoint is checked again (polled for up to 5s). If it still isn't met -> `FAILURE`.
    4. `risky_confirmation`: The run is confirmed, and replay starts at step 1.

- On `abort`, the run ends: discovery stops with `aborted_by_operator` and nothing is recorded; replay returns `FAILURE` with the reason.


### What's recorded
Every escalation is appended to the run's result.json with the request, the operator's decision, and their note:
```
    {
      "reason": "replay_failure",
      "capability_or_goal": "parabank.request_loan",
      "current_step": 3,
      "current_url": "http://localhost:8080/parabank/requestloan.htm",
      "detail": "Step 3 (select_option) failed: The dropdown has 14 option(s): ['12456', '12567', '12678', '12789', '12900', '13011', '13122', '13233', '54321', '13566', '12345', '13677', '13788', '13344']. '99999' isn't one of them. | raw error: TimeoutError: Locator.select_option: Timeout 5000ms exceeded.",
      "screenshot_path": "evidence/replay_request_loan_20260925T034756Z_8deaf537c58b/escalation_3de8c79df3c64363a3670539d2e0efa6.png",
      "timestamp": "2026-09-25T03:48:09.469175+00:00",
      "operator_decision": "abort",
      "human_actions": []
    }
```
### Limits
1. **The operator can't complete steps in the browser.** They can type into fields and choose from dropdowns, but links and buttons don't load anything while the prompt is waiting: each request is held until the operator answers. The operator's only real input is the decision to continue (`resume`) or stop (`abort`).
2. **Held requests go through after the answer.** If the operator clicked "Apply Now" during the prompt, the loan can be submitted after the run has already reported its result.
3. **Only the operator's note is recorded.** The optional note is saved with the escalation in `result.json` as an audit record, but the system doesn't act on it. The operator's actual clicks and typing aren't recorded.
4. **The operator must be at the same computer.** The prompt appears in the terminal that started the run, and the browser opens on that screen. A production version needs a web console for operators; the assignment allows this to be mocked.
5. **No time limit.** The run waits for an answer indefinitely.


## 6. Safety
There are three safeguards: a list of allowed pages and actions, approval for risky capabilities, and keeping sensitive values out of saved files.

### Allowed pages and actions
`config/allowlist.yaml` lists the sites, pages, and actions the system may use. Every action is checked against it first. Links and new windows that lead to a page not on the list are stopped before the page loads; this also applies to the operator during a handoff. A server can still redirect to another page, so the address is checked again after each action.

In replay, a blocked action ends the run immediately, and the operator can't override it. In discovery, the agent is told the action failed and can try another way.


### Risky capabilities need approval
Partially discussed in Section 5, Capabilities that move money or open accounts (loan requests, transfers, bill payments, new accounts) are marked risky, based on their name. Before one runs, the operator sees exactly what will be submitted and the current account balance, and must approve it. Blocking these capabilities would make them useless, and only flagging them would let a loan be requested without anyone checking. A caller that already has approval can skip the prompt with `--confirmed`.

### Sensitive Data
1. Saved capabilities contain placeholders like `{password}` instead of real values. If a password would otherwise end up in the file, recording fails.
2. Run logs hide passwords, PINs, social security numbers, card-length numbers, and login credentials wherever they appear:
    ```
      "inputs": {
        "username": "john",
        "password": "[REDACTED]"
      },
    ```

### Limits
1. Discovery doesn't need approval. The agent completes the task itself, so discovering the loan capability requested a real loan. Discovery of risky capabilities should need approval or run only in a test environment.
2. Page content is sent to the AI model. During discovery, names, balances, account numbers, and the login credentials go to Anthropic's API. 
3. Screenshots aren't redacted. They show names, balances, and account numbers.
4. Some sensitive data isn't recognized. ParaBank's 5-digit account numbers, names, and addresses appear in logs.
5. Risk depends on the capability's name. A risky capability with an unexpected name is treated as safe.

## 7. Cuts
1. Automated tests. Behavior was checked with one-off scripts against the local ParaBank. They should become a test suite.
2. Some outputs are guessed from their names. If no step reads an output from the page, an output named like login_succeeded is set to "true" or "false" from the run's result, and any other output comes back empty. Each output should state where its value comes from.
3. loan_status copies the run's result. Reading the status from the page sometimes returns the label ("Status:") instead of the value, so it's taken from the result instead. Once page reading is reliable, it should come from the page.
4. Loan wording in shared code. The approval message ("This will submit a NEW loan application…") is written into code that every capability uses. Each capability should define its own.
5. An operator web page, recording the operator's actions, and the done answer (Section 5).
Handling known interruptions automatically, such as confirmation boxes or expired sessions.
6. Today they fail the step and go to the operator.
7. Other apps and multiple clients (Section 4): designed, not built.
8. Safer discovery: approval before risky submissions, and hiding sensitive data from the AI model and from screenshots (Section 6).
9. **Approval before unattended runs.** Risky capabilities always need an operator's confirmation. To let them run unattended, each capability would start as a draft and be marked approved by a reviewer once it replays reliably, with the approval recorded.
