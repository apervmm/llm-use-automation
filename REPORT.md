

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
  - `Step.target` reuses the exact `ElementRef` (locator strategy +
    fallback chain) that already worked live during discovery, rather
    than re-deriving a locator at replay time. The artifact freezes
    what was proven to work.
  - `Step.value` holds either a literal or a `"{param}"` placeholder.
    Parameterization is explicit and human-driven — a `param_map`
    supplied at recording time — not inferred automatically, trading a
    manual step for a reviewable one.
  - `OutputField.derived_from_outcome` lets one output type cover two
    cases: a value read directly off the page (`derived_from_outcome=False`),
    or a value inferred from which `outcome_rule` matched
    (`derived_from_outcome=True`, e.g. `loan_status`) — avoiding a
    second output type for what is still fundamentally one named value.
  - `checkpoint` and `outcome_rules` are deliberately split rather than
    folded into one field: `checkpoint` is the single condition
    defining success, checked first; `outcome_rules` is a closed,
    named set of legitimate non-success results (e.g.
    `insufficient_funds`), checked only if the checkpoint is missed.
    This makes the business-outcome-vs-failure distinction structural,
    not something replay logic has to infer per capability.
  - `InputParam.example` is redacted at record time
    (`"[REDACTED]"`) for any field named `password`/`pin`/`ssn`, so a
    sensitive value never lands in a saved artifact even as a sample.
  - `InputParam.required` isn't decorative — `executor.py` checks it
    before replay runs, failing fast if a required input is missing
    rather than letting a partial run start.

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
*what you deliberately left out, and what you'd build next*
