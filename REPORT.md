

## 1. Architecture
The system runs a task in two ways. In discovery, an AI agent works out how to complete a goal in the browser, and its successful run is saved as a capability. In replay, a saved capability runs again with new inputs, step by step, without the AI.

<p align="center">
    <img width="960" height="900" alt="image" src="https://github.com/user-attachments/assets/3a25da69-b092-405a-bc26-be65aba16ace" />
</p>

- **Agent (`src/agent/`):** on each turn, it describes the page to the model in text, together with the goal, and gets back exactly one action: `click`, `type_text`, `navigate`, `read`, `select_option`, or `done`. The description lists the page address, its title, the elements that can be clicked or typed into, and the start of the page text. Screenshots are saved as evidence but not sent to the model. The agent stops when the model says done (the CLI then checks the page to confirm success), when it has used its 15 steps or failed 3 actions in a row (both first ask a person for help), when the operator stops it, or when the start page can't be reached.

- **Replay (`src/replay/`):** checks the caller's inputs, asks for approval if the capability is risky, runs the saved steps in order, and reports one of three results (Section 3).

- **Recorder and store (`src/artifact/`):** turn a successful agent run into a Capability artifact (Section 2) and save it as a new version in /artifacts/.
  
- **Surface (`src/surface/`):** is `BrowserSession` together with `perception.py`: a wrapper around one Playwright browser session. Agent, Replay, and the escalation module act on the page only through it; nothing outside `src/surface/` calls Playwright directly. It provides:
  1. **Actions**: `click`, `type_text`, `select_option`, `read_text`, and `goto`. Each checks the allowlist first and returns an ActionResult.
  2. **Observation**: `perception.snapshot(session)` builds a PageState for the agent: the interactive elements (each with a locator and fallbacks), the visible text, and a screenshot.
  3. **Helpers** used by replay and escalation: `get_url`, `get_visible_text`, `wait`, `is_visible`, `screenshot`, `bring_to_front`, and `pop_dialogs`, which reports any JavaScript dialog that appeared and was dismissed.

- **Escalation (`src/escalation/`):** pauses the run and asks a person when the system is stuck or needs approval (Section 5).
  
- **Safety (`src/safety/`):** the allowlist and the hiding of sensitive values (Section 6).
  
- **CLI (`src/cli.py`):** the `discover` and `replay` commands. Each run saves its evidence in its own folder in /evidence/.

**Key decisions and trade-offs:**
- **A fixed set of actions.** Each turn, the model must pick one of six actions instead of replying in free text, so every action maps directly to a step that can be replayed. Cost: actions outside the set, such as drag-and-drop, aren't possible.
- **The model reads text, not screenshots.** It picks from a list of named elements, and each one already carries saved ways to find it again. So anything the agent does can be replayed without AI. Cost: the model can't use purely visual cues, such as an unlabeled icon.
- **Surface controls the browser** Only `src/surface/` talks to the browser. Supporting a desktop app would mean writing a new version of that layer, without changing the agent, the capability format, or replay. Cost: every action goes through this layer, even where a direct call would be simpler.
- **A config file per capability.** A person writes a short file for each task, `capabilities/login.yaml`, and `capabilities/loan.yaml`: the goal, the start page, which values are inputs, how success is checked, and which answers are normal results. The agent only finds the steps. The decisions that make replay trustworthy stay with a person. Cost: a new config for every new capability.


## 2. Artifact schema

A capability such as `artifacts/parabank.request_loan.v1.json` is one JSON file per version. It's written to be read by two audiences: a person reviewing it, and a program calling it. Both can see what it does, what it needs, what it returns, and how success is judged.

### Capability Structure
1. `capability_id` and `version`: The name, always starting with the app (parabank.request_loan), and a version that goes up each time it's recorded again
2. `description`: The discovery goal, with recorded values replaced by placeholders (amount '{amount}')
3. `target_app` and `entry_url`: The app, and the page replay starts from
4. `inputs`: What the caller must provide: name, type (number or string), whether it's required, and an example
5. `outputs`: What replay returns, and where each value comes from
6. `steps`: the recorded actions, in order
7. `checkpoint`: The one condition that means success, e.g. the page shows "Congratulations, your loan has been approved"
8. `outcome_rules`: Known answers that aren't success, e.g. insufficient_funds
9. `risk_level`: safe or risky, set automatically (Section 6)
10. `created_at`:When it was recorded

### Step Structure
1. `step_num`: The step's position. Replay runs steps in this order, and two steps can't share a number
2. `action`: What to do: `click`, `type_text`, `select_option`, `navigate`, or `read`
3. `target`: The element to act on (empty for `navigate`, and for a `read` that isn't tied to an element):
    - `strategy` and `value`: The main locator: how to find the element (`css`, `role_name`, or `text`) and what to look for, e.g., `#fromAccountId`.
    - `role`: The element's type, like button, link, or `combobox` (dropdown)
    - `expected_name`: The element's visible name, checked when a button or link is found by a fallback
    - `fallbacks`: Other locators to try in order if the main one fails, each with the same fields
4. `value`: What to type or select, usually a placeholder such as `{from_account_id}`, filled from the caller's inputs
5. `read_label`: For `read` steps, the name the value is saved under and matched to an output (empty otherwise)
6. `description`: A readable summary. When a step fails, replay fills in the caller's actual values, e.g. `Select '99999' in 'From account #:'`.


### Why are Capability and Step shaped this way?
1. A saved version is never changed. Recording again creates `v2`, so older versions still replay exactly as before.
2. Inputs are declared once in the `inputs` list (name, type, whether required, an example), and the steps refer to them by placeholder, like `"value": "{amount}"`. The values themselves arrive only at replay. So a caller can see what to provide without reading the steps, the same recording works with any amount, and no step contains a password or account number.
3. Outputs are also listed separately from the steps, so a caller can see what comes back without reading how it's produced.
4. Each step stores a main locator plus `fallbacks`, tried in order if the main one stops working. Each locator records its kind (`strategy`) separately from its `value`, so another type of software, such as a desktop program, only needs new kinds of locators, not a new format (see Section 4).
5. Capability should be able to judge different types of results, not only what succeeded, but also expected "no" answers (business outcomes), so anything else can be reported as failure (see Section 3)
6. The start page should be separate from the steps, since it tells the condition to start from, but not the action to take at each step. And keeping it apart helps the address change per client (see Section 4)
7. The risk level is stored in the file, since anyone reading or calling the capability sees that it's risky before running it. Also, it helps to construct the logic around **Human-In-The-Loop** (see Section 5)
8. Each capability should be single-purposed, such as logging in or requesting a loan. One that depends on another names it instead of copying its steps: `capabilities/loan.yaml` sets `auth_capability_id: parabank.login`, and the CLI replays the login first. A change to the login is then made in one place, and capabilities can be combined and chained.



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
4. Only the run's own account numbers are masked. Account numbers the run uses (its inputs and outputs) keep only their last 2 digits in logs (`***44`). Other account numbers that appear in page text, such as the options listed in a dropdown error or the account table in discovery logs, stay visible. Names and addresses aren't recognized either.
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
