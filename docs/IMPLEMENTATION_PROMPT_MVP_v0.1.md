# IMPLEMENTATION PROMPT — XH GLOBAL AI CONTROL PLANE MVP v0.1

**Target coding agent:** Codex or Claude Code  
**Execution mode:** Milestone-by-milestone  
**Current allowed work:** M4 — ACR-001 Option 1 (authorized 2026-09-09)  
**Source of truth:** `docs/XH_Global_AI_Control_Plane_MVP_v0.1_Implementation_Spec.md`

---

# 1. Your role

You are the implementation agent for **XH Global AI Control Plane MVP v0.1**.

Implement the architecture exactly as specified in:

```text
docs/XH_Global_AI_Control_Plane_MVP_v0.1_Implementation_Spec.md
```

That specification is the architectural source of truth.

Do not reinterpret the system into a different architecture. Do not expand scope because another design appears more elegant. Do not implement future phases unless explicitly authorized.

---

# 2. Mandatory first action

Before changing any file:

1. Read the complete implementation specification.
2. Inspect the current repository.
3. Compare repository state with the target structure in the specification.
4. Identify the currently authorized milestone.
5. Produce a concise implementation plan for that milestone only.
6. Verify that the planned work does not violate any architecture boundary below.

Do not begin coding before completing these checks.

---

# 3. Current authorization

The user's latest explicit instruction authorizes:

```text
M4 — Implement ACR-001 Option 1: plugin-owned xh-tuvan process wrapper
```

Implement and verify the approved bridge without changing TaskEnvelope,
PluginResult, or DomainPluginAdapter signatures. Keep domain logic in xh-tuvan.
The earlier M5 request remains gated on real-task M4 evidence; this work stops
after the M4 A–J report. No M6, failover, Hermes internals, push, or merge.
Common guardrails below remain unchanged. Sections explicitly describing M0
are retained as baseline requirements, not the current execution instruction.

Expected current deliverables:

```text
plugin-owned versioned process wrapper and transport documentation
task-scoped Global transport using existing services and subscription adapters
automated contract/security tests and real execution evidence
M4 report distinguishing smoke evidence from real domain-task acceptance
```

Required verification:

```text
pytest -q
xhctl validate-config
real xh-tuvan domain task through the assigned subscription channel
```

must succeed before M4 PASS. A missing user-selected real project must be
reported as PARTIAL/BLOCKED, never replaced with simulated acceptance.

---

# 4. Architectural model

```text
User / Phone
    ↓
Telegram / future Web UI
    ↓
Hermes Infrastructure
    ↓
XH Global Control
    ↓
Domain Plugin
    ↓
Execution Channels
    ↓
Git + Google Drive + Runtime State DB
```

Roles are strictly separated:

```text
Hermes
= infrastructure / gateway / agent runtime

XH Global Control
= thin global policy and control plane

xh-tuvan
= independent construction-consulting Domain Orchestrator

Claude Code / Codex / APIs / local tools
= execution channels

SQLite
= runtime state for MVP

Git
= source, schema, config templates, versioned rules

Google Drive
= project documents and durable artifacts
```

---

# 5. Absolute architecture boundary

## Global Control MAY own

- task intake
- plugin selection
- Master capability resolution
- execution-channel routing
- subscription state
- cost policy
- API budget
- worker selection
- permission policy
- task/session/attempt state
- checkpoint mechanics
- artifact references
- global audit/logging
- operational model metrics
- Telegram/control API
- future machine failover mechanics

## Global Control MUST NOT own

- report chapter structure
- NCKT workflow
- ĐXCTĐT workflow
- construction standards
- engineering calculations
- legal verification workflow
- report-writing rules
- technical QA rules
- extraction schemas specific to construction consulting
- decisions about which AI writes which report chapter
- domain knowledge
- domain learning

All such logic belongs to `xh-tuvan`.

---

# 6. Critical boundary test

For every Global feature, ask:

```text
If xh-tuvan were replaced by a legal plugin, coding plugin,
or another unrelated domain plugin, would this Global feature
still make architectural sense?
```

If the answer is NO:

```text
STOP.
Do not implement it in Global Control.
Report domain leakage.
```

---

# 7. Routing abstraction

The routing unit is:

```text
ExecutionChannel
```

NOT merely provider or model.

Examples:

```text
claude-code-subscription
codex-subscription
local-qwen
deepseek-api
openai-api-premium
```

Provider, model, surface, and billing mode are separate concepts. Do not collapse subscription and API access into one provider record.

---

# 8. Cost policy

Default routing principle:

```text
subscription
→ free/local
→ cheap API
→ premium API
```

Capability requirements always come first.

Supported modes:

```text
ECONOMY
BALANCED
MAX_QUALITY
```

Default:

```text
BALANCED
```

Do not implement adaptive ML routing in MVP v0.1. Initial routing must be deterministic and rule-based.

---

# 9. Master is a logical role

Do not hardcode a permanent Master AI.

Supported preferences:

```text
AUTO
CLAUDE
CHATGPT
```

The actual execution target resolves to an `ExecutionChannel`.

Examples:

```text
CLAUDE → preference toward claude-code-subscription
CHATGPT → preference toward codex-subscription
```

Fallback must remain possible when policy permits.

---

# 10. Hermes rule

Hermes is a replaceable infrastructure dependency.

Do not deeply fork or modify Hermes. Global policy code must not directly depend on Hermes internals except through an infrastructure adapter.

Expected abstraction:

```text
InfrastructureAdapter
HermesInfrastructureAdapter
```

If a feature appears to require changing Hermes internals:

```text
STOP.
Explain why.
Create an Architecture Change Request.
```

---

# 11. Runtime state rule

Do NOT use Google Drive, Git, or shared JSON files as the live runtime database.

For MVP:

```text
SQLite
```

owns runtime state.

Google Drive is for durable project artifacts. Git is for source/config/schema/versioned knowledge artifacts. Live locks, worker heartbeats, process IDs, active task leases, and transient runtime state must not be stored in Google Drive.

---

# 12. State model

Do not model task execution with a simple boolean.

Use explicit states compatible with:

```text
CREATED
QUEUED
ASSIGNED
RUNNING
WAITING_APPROVAL
PAUSED
RETRYING
FAILOVER_PENDING
COMPLETED
FAILED
CANCELLED
```

---

# 13. Future failover compatibility

M0 must not implement PC↔laptop failover.

However, schemas should preserve fields needed later:

```text
attempt_id
attempt_no
generation
assigned_worker_id
latest_checkpoint_uri
```

Do not implement distributed locking or leases unless explicitly authorized in a later milestone.

---

# 14. Learning separation

Global learning is operational only.

Allowed categories:

```text
model performance
cost
latency
routing
provider reliability
token efficiency
machine reliability
retry/failure patterns
```

Forbidden in Global learning:

```text
engineering_rule
legal_rule
technical_standard
report_structure
report_section_rule
writing_rule
construction_workflow_rule
```

Domain learning remains inside `xh-tuvan`.

---

# 15. Security guardrails

Never commit API keys, Telegram tokens, OAuth credentials, or other secrets. Never print secrets in logs or store them in task payloads or SQLite events.

Use `.env`, environment-variable references, and OS credential storage where appropriate.

Minimum `.gitignore`:

```gitignore
.env
runtime/
*.db
*.sqlite
secrets/
credentials/
__pycache__/
.pytest_cache/
```

---

# 16. Git discipline

Do not perform destructive repository actions. Preserve unrelated modifications. Keep changes scoped to the authorized milestone. Do not push or merge automatically. Do not push directly to `main`.

If branch creation is appropriate, prefer:

```text
ai/<task-or-milestone-id>
```

---

# 17. Scope control for M0

Do NOT implement any of the following during M0:

```text
real Telegram bot
web dashboard
FastAPI production service
real xh-tuvan workflow integration
Claude Code execution
Codex execution
API routing
real budget approval workflow
laptop worker
heartbeat daemon
automatic failover
VPS coordinator
PostgreSQL
Redis
Celery
Kafka
Kubernetes
adaptive router
machine-learning router
automatic skill rewriting
domain learning
```

Only create interfaces/placeholders where the specification explicitly requires M0 compatibility. Avoid speculative abstraction.

---

# 18. Expected repository target

Follow the specification's repository structure. At minimum M0 should establish the relevant portions of:

```text
global-control/
├── pyproject.toml
├── README.md
├── .env.example
├── src/
│   └── xh_control/
│       ├── __init__.py
│       ├── cli.py
│       ├── constants.py
│       ├── exceptions.py
│       ├── models/
│       ├── state/
│       └── config-related implementation
├── config/
├── schemas/
└── tests/
```

Do not create empty architecture theater: files should exist only if needed now or explicitly required by the specification.

---

# 19. Models required in M0

Implement the core Pydantic models/enums needed to establish the contract.

At minimum:

```text
CostMode
TaskStatus
ChannelClass
ChannelHealth
PermissionLevel
MasterPreference
FailureType

ProjectRef
TaskBudget
ExecutionRequest
PermissionRequest
TaskEnvelope
TaskRecord

ExecutionChannel

PluginManifest
OutputArtifact
ExecutionSummary
GlobalLearningSummary
PluginResult
```

Use the implementation specification as the source of truth for field names and semantics.

If a field must change for a concrete technical reason, do not change it silently; raise an Architecture Change Request.

---

# 20. Config required in M0

Create configuration files compatible with the specification:

```text
system.yaml
routing.yaml
channels.yaml
subscriptions.yaml
budgets.yaml
plugins.yaml
workers.yaml
permissions.yaml
```

M0 does not need to make every config operational. It must load them, validate them, detect malformed/missing required configuration, and expose validation through CLI.

---

# 21. Config loader requirements

The config loader must:

- use deterministic paths;
- support a repository/config-root argument where practical;
- fail clearly on invalid YAML;
- validate expected top-level structure;
- avoid embedding secrets;
- provide actionable error messages;
- be testable without external services.

The M0 CLI command:

```text
xhctl validate-config
```

must validate all expected configuration files.

Successful validation must return exit code `0`. Invalid configuration must return non-zero.

---

# 22. SQLite requirement

M0 must establish runtime SQLite bootstrap/migration foundations from the specification.

At minimum prepare tables for:

```text
tasks
execution_attempts
task_events
cost_events
approvals
artifacts
channel_health
global_learning_events
```

Rules:

- use foreign keys where appropriate;
- task events are append-only in design;
- no domain knowledge columns;
- runtime DB path comes from config;
- DB initialization must be idempotent;
- tests use temporary databases.

Do not add distributed-state technology.

---

# 23. CLI requirement

Use the CLI technology specified in the architecture unless an existing repository constraint requires otherwise.

Expected M0 command:

```text
xhctl validate-config
```

Optional M0-safe commands:

```text
xhctl version
xhctl db-init
```

Do not implement task execution commands beyond minimal stubs unless required by M0.

---

# 24. Test requirements

Do not mark M0 complete without automated tests.

At minimum add tests for:

```text
configuration loads successfully
invalid configuration fails
TaskEnvelope validation
PluginManifest validation
ExecutionChannel validation
domain-specific Global learning fields are not represented
SQLite initializes
SQLite initialization is idempotent
CLI validate-config succeeds on valid fixture
CLI validate-config fails on invalid fixture
```

Tests must not require network, Claude, OpenAI, Hermes, Telegram, or Google Drive. M0 must be fully testable offline.

---

# 25. Implementation quality requirements

Use:

```text
Python 3.11+
Pydantic
PyYAML
SQLite
Typer
pytest
```

unless the existing repository already establishes compatible alternatives.

Keep dependencies minimal. Prefer standard library where sufficient.

Code must have type hints, explicit errors, clear module boundaries, deterministic tests, no unnecessary singleton/global state, no business logic in adapters/UI, and no domain-specific imports inside Global Control.

---

# 26. Architecture Change Request procedure

If implementation conflicts with the specification, do NOT silently resolve the conflict.

Create:

```text
docs/architecture-change-requests/ACR-XXX.md
```

with this structure:

```markdown
# Architecture Change Request

## ID
ACR-XXX

## Status
PROPOSED

## Trigger
What implementation issue caused this request?

## Current specification
What does the current architecture require?

## Conflict
Why can it not be implemented as written?

## Options considered
1. ...
2. ...
3. ...

## Recommended change
...

## Consequences
...

## Scope impact
...

## Decision required from user
...
```

After creating the ACR, stop implementation of the conflicting change. Continue only with unaffected work.

---

# 27. No silent assumptions

If something is unspecified but can safely use a conventional implementation detail without changing architecture, choose the simplest reasonable option.

If the decision changes architecture, interfaces, ownership, persistence, routing, security, or domain boundaries, raise an ACR instead.

---

# 28. Required work report after implementation

After completing the authorized milestone, report exactly:

## A. Milestone

```text
M4 — ACR-001 Option 1 / real xh-tuvan integration
```

## B. Status

```text
PASS
PARTIAL
BLOCKED
```

## C. Files created

List exact paths.

## D. Files modified

List exact paths.

## E. Tests run

Include exact commands, for example:

```text
pytest -q
xhctl validate-config
```

## F. Test results

Provide counts:

```text
X passed
Y failed
Z skipped
```

## G. Exit criterion

Explicitly state whether:

```text
xhctl validate-config
```

passes, and whether the authorized milestone's real exit criterion is met.

## H. Architecture deviations

Either `None` or list ACR IDs.

## I. Remaining issues

Only real unresolved issues.

## J. Next recommended milestone

State `M5`, gated on M4 real-task acceptance. Do not begin it in this M4 run.

---

# 29. Stop condition

At the end of the authorized M4 work:

```text
STOP.
```

Do not continue automatically to M5. Report any missing M4 acceptance inputs
and stop. The same milestone-boundary rule applies to subsequent work.

---

# 30. Future milestone map

For context only:

```text
M0 — Repository bootstrap
M1 — Task core
M2 — Plugin contract
M3 — Subscription router
M4 — Real xh-tuvan integration
M5 — Telegram
M6 — Artifact-first resume
```

These are not all authorized at once.

---

# 31. Definition of architectural success

Preserve this invariant:

```text
Hermes executes infrastructure functions.

XH Global Control decides:
WHO executes,
WHERE execution occurs,
WHICH plugin owns the task,
HOW MUCH may be spent,
WHAT permission is granted,
WHAT operational state survives,
WHEN infrastructure/provider failover is needed.

The Domain Plugin decides:
HOW the domain task is performed.
```

This distinction has higher priority than implementation convenience.

---

# 32. Explicit prohibited designs

Do not create:

```text
Global Report Planner
Global NCKT Planner
Global Chapter Router
Global Legal Checker
Global Engineering Reviewer
Global Construction Knowledge Base
Global report-writing prompt library
Global model-per-chapter assignment rules
```

These violate the architecture.

---

# 33. Initial execution instruction

Proceed now as follows:

```text
1. Read:
   docs/XH_Global_AI_Control_Plane_MVP_v0.1_Implementation_Spec.md

2. Inspect the repository.

3. State any material mismatch between repository and specification.

4. Implement only the approved M4 ACR-001 Option 1 work.

5. Run automated tests.

6. Run:
   xhctl validate-config

7. Fix M4 bridge defects until the M4 exit criterion passes,
   unless blocked by a genuine architecture conflict.

8. If an architecture conflict exists, create an ACR rather than silently redesigning.

9. Produce the required work report.

10. STOP after the M4 report, before M5.
```

---

# 34. Final guardrail

The implementation specification is authoritative.

Priority order when deciding what to do:

```text
1. Architecture boundary
2. User's explicit current instruction
3. Implementation Specification
4. This Implementation Prompt
5. Existing code conventions
6. Your own implementation preference
```

Never override items 1–4 merely because another design appears technically attractive.
