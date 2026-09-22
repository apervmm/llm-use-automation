

## 1. Architecture
Based on the assignment specification, the system has to have two distinct flows of the execution: non-deterministic llm `agent` to generate `artifact`, and deterministic `replay` mechanism to use this the same artifact for reproduction. The system is restructured into independent modular components that gets used as shown in diagram below.

![Flowchart](./static/architecture.png)

**Agent:** takes a goal and a starting URL. On each turn it takes a snapshot of the current page, sends that state plus the goal to the model, and asks for one next action from a fixed set: `click`, `type_text`, `navigate`, `read`, `select_option`, or declare the goal done. It executes that one action, records whether it succeeded, and feeds the result back in before asking for the next actio and repeats until:
```
1. the model reports the goal is done
2. the step limit (15) is reached — extendable by 3 more steps if a human resumes from escalation
3. 3 consecutive failed actions occur — also escalates to a human
```

**Replay:** Takes a saved artifact — loaded by capability ID from the `/artifacts/` store — and a set of input values supplied by the caller at invocation time `--input` flag. It walks the artifact's steps in the recorded order, substituting each input into the step that expects it, and executes each step against the same kind of session the agent used. After the last step, it checks whether the artifact's declared condition for success actually holds on the page. 

If it does, replay reports success along with whatever outputs the artifact declares. 
If it doesn't, replay checks whether the page instead matches one of the artifact's declared business outcomes (e.g. a rejection or a not-found result) before concluding it's a real failure. An unrecoverable failure, or a step marked risky without prior confirmation, can also trigger a handoff to a human mid-replay.

**Surface:** is the layer where both Agent and Replay act on — a single wrapper around one browser session that neither of them bypasses, where their interactions on the actions are exectuted through actions methods `read_text`, `click`, `goto`, `select_option`, or `type_text`.

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

**CLI:** is an orchestrator layer that brings `surface`, `artifacts`, `agent`, and `replay` together.



## 2. Artifact schema

The main artifact is `Capability`, which is a versioned and typed schema that consists of 13 fields:

```
class Capability(BaseModel):
    capability_id: str                     
    version: int = 1
    description: str = ""
    target_app: str = "parabank"
    entry_url: str

    inputs: list[InputParam] = Field(default_factory=list)
    outputs: list[OutputField] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    checkpoint: Optional[Checkpoint] = None

    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: Literal["llm_discovery"] = "llm_discovery"
    outcome_rules: list[OutcomeRule] = Field(default_factory=list)

    risk_level: RiskLevel = RiskLevel.SAFE
```

Each `Step.target` is an `ElementRef` — the same locator structure
(CSS primary, role/text/XPath fallbacks) already resolved live during
discovery. The artifact freezes what was proven to work rather than
re-deriving targeting logic at replay time.

Parameterization is explicit, not inferred: a human-supplied
`param_map` (literal → name) turns concrete values like `"john"` into
placeholders like `"{username}"` when a capability is recorded. The
same applies to a value chosen mid-run from a dropdown (`select_param`
in the recording config) — whatever the agent actually selected becomes
the parameterized value, rather than a value assumed in advance.

Outputs come in two forms sharing one `OutputField` type:
`derived_from_outcome=False` outputs are lifted from a recorded `read`
step, while `derived_from_outcome=True` outputs (e.g. `loan_status`)
are inferred from which `OutcomeRule` matched — avoiding a second output
type for something that is still fundamentally "one named value."

`checkpoint` and `outcome_rules` are deliberately split: checkpoint is
the single definition of success, checked first; outcome_rules is a
closed, named set of alternate legitimate results (e.g.
"insufficient_funds"), checked only if the checkpoint is missed. This
keeps the business-outcome-vs-failure distinction structural rather
than something the replay logic has to infer per capability.

`risk_level` is computed automatically at record time from
`allowlist.yaml`'s risky-capability patterns, rather than set by hand —
so a capability can't accidentally be recorded as `safe` by omission.

Artifacts are versioned by filename (`<capability_id>.v<N>.json`),
auto-incremented by `store.save()`, so re-recording a changed flow
produces a new, inspectable version rather than overwriting history.

**Design choice — composition lives outside the schema.** A capability
that depends on another (e.g. `parabank.request_loan` needs
`parabank.login` first) doesn't embed the dependency's steps. Instead,
the capability's *recording config* (a separate YAML, not the artifact
itself) names an `auth_capability_id`, which the CLI replays first.
This keeps each saved `Capability` single-purpose and independently
replayable, at the cost of that dependency being declared outside the
artifact schema rather than as a first-class field on it.



![Schema](./static/schema.png)


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
