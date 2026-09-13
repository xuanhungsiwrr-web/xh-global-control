# XH Global AI Control Plane

This repository contains the thin global policy and control plane described by
the MVP v0.1 implementation specification. M0-M3 establish configuration,
task/plugin contracts, deterministic subscription routing, and persistent budget
policy. The environment-independent portion of M4 adds real non-interactive
subscription channel execution, worker/permission enforcement, output artifact
registration, and operational metrics.

## Setup

Requires Python 3.11 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pytest -q
xhctl validate-config
```

Initialize the configured SQLite database with:

```powershell
xhctl db-init
```

Create a persistent task and its initial audit event without executing a plugin:

```powershell
xhctl run --dry-run --plugin xh-tuvan --project PROJECT-X --task "Opaque request"
```

M1 performs no network calls and does not execute domain plugins, execution
channels, routers, Telegram handlers, or automatic failover.

Run the offline M2 contract integration test with:

```powershell
pytest -q tests/integration/test_m2_plugin_flow.py
```

M2 provides `PluginRegistry`, the async `DomainPluginAdapter` interface, and a
mockable contract runner.
The runner verifies plugin/interface/task-type compatibility, revalidates every
`PluginResult`, rejects cross-task results, registers only opaque artifact
references, and records sanitized audit summaries. Rejected result content is
never copied to audit events.

M3 provides `ClaudeCodeAdapter` and `CodexAdapter` auth-status healthchecks,
`ChannelRouter`, `MasterSelector`, and `BudgetEngine`. Routing filters disabled,
incapable, unavailable, rate-limited, and active-cooldown channels. It then uses
the hard class order `subscription → free/local → cheap API → premium API`
before deterministic within-class scoring, so a capable subscription cannot be
overtaken by an API score. `CLAUDE` and `CHATGPT` remain logical preferences with
policy-controlled fallback. `ECONOMY`, `BALANCED` (default), and `MAX_QUALITY`
reuse the configured mode policy.

Healthchecks invoke only supported local CLI auth-status commands (`claude auth
status --json` and `codex login status`). Claude JSON is parsed in memory only to
read `loggedIn`; raw stdout and all stderr are never returned or persisted. The
checks never start an LLM task and explicitly report that quota was not checked.
Simulated health in automated tests is separate from environment probing.

`BudgetEngine` evaluates the resolved task budget plus configured daily and
global-monthly scopes independently. Any crossed hard limit creates a pending
`EXCEED_API_HARD_LIMIT` approval and atomically moves a running task to
`WAITING_APPROVAL`; zero-cost subscription/local authorization remains allowed.
Actual costs, warnings, approvals, and state changes are stored in SQLite audit
records. Paid API execution itself is not implemented in M3.

M4 channel execution uses `codex exec` or Claude Code print mode through the
`ExecutionChannelAdapter` contract. Instructions are passed on stdin, execution
does not block the event loop, stderr is not persisted, and output is stored as
an opaque artifact reference. SAFE_EDIT keeps the model-facing project workspace
read-only; PROJECT_WRITE must be requested explicitly. Elevated permissions and
paid channels are rejected unless their approval/budget paths authorize them.
Measured latency and reported token counts are persisted without inventing
missing usage or API cost.

ACR-001 Option 1 is approved. The `xh-tuvan` 0.9.0 source has a separate
plugin-owned process wrapper at `bridge/wrapper.py`; `config/plugins.yaml`
points to the current XHOME-PC source checkout. Global launches
it with the current Python interpreter and a task-scoped context, then brokers
one call through the assigned subscription channel. `ProcessExecutionService`
composes registry, permissions, worker/router, attempt, channel, cost and audit
services. It validates the returned result and artifact hash and finalizes both
task and attempt. No domain instructions are stored in Global source.

Run a pre-approved TaskEnvelope JSON locally:

```powershell
.\.venv\Scripts\python.exe -m xh_control.interfaces.process_cli --envelope <absolute-task.json>
```

For isolated live evidence, use `scripts/verify_m4_bridge.py --workspace <path>
--request <request> --evidence-root <new-directory>`. It defaults to SAFE_EDIT
(read-only project), AUTO, BALANCED and configured plugin budgets. A successful
smoke test is not real project acceptance; inspect the domain artifact against
the actual request. Missing plugin gates produce FAILED, never fabricated PASS.
M4 process abort waits for the owned process trees to exit and records FAILED;
safe-stop/checkpoint and restart resume remain later milestone work.

The Codex process bridge excludes user MCP/apps/provider overrides, retains the
Windows elevated sandbox implementation and uses the task's sandbox permission.
External connector-dependent domain workflows will report their missing gates.
See `docs/milestone-reports/M4_OPTION1_BRIDGE_REPORT.md` for current acceptance.

## Configuration and state

All eight YAML files in `config/` are required. They follow section 11 of the
implementation specification. Plugin entries and worker paths are configuration
metadata; validation does not import plugins or require those paths to exist.

The default config directory is resolved from the package location, independently
of the current working directory. For an installed package outside this checkout,
or a separate configuration directory, pass an explicit root:

```powershell
xhctl validate-config --config-root D:/XH-AI/global-control/config
xhctl db-init --config-root D:/XH-AI/global-control/config
```

Relative `system.sqlite_path` values resolve against the configuration directory's
parent. Absolute paths are used directly. `validate-config` never creates runtime
state. `db-init` creates the eight specified tables in one transaction and records
schema version 2 with SQLite `user_version`; repeating it preserves existing data.
Set `XH_CONTROL_RUNTIME_ROOT` to an absolute host-local directory to keep the
default SQLite database and transient channel artifacts off a synced checkout;
an explicit `--config-root` remains isolated and ignores this host override.
Task-event updates and deletes are rejected by SQLite triggers. Future database
connections must enable `PRAGMA foreign_keys = ON` to enforce foreign keys.

The JSON schemas in `schemas/` mirror the M0 Pydantic contracts. Handoff behavior
and its schema are deferred to M6. Global-learning payloads reject undeclared
top-level fields and the specification's forbidden domain keys at any depth.
Do not put credentials in configuration or payloads. Configuration errors report
locations and error types without echoing supplied values.

Schema version 2 adds task-core indexes and database enforcement for positive,
unique attempt numbers and generations. `TaskService` centrally validates state
transitions, assigns monotonically increasing attempts/generations, and rejects
stale attempt-generation fencing tokens. Task creation, transitions, attempts,
artifact references, checkpoint references, and audit events survive process
restart in SQLite. Artifact records contain references and hashes, never artifact
contents.

The automated tests use temporary databases and block network connections. Real
channel smoke tests are separate from pytest. Telegram and artifact-first resume
remain outside M4.

## Hermes gateway integration

Hermes owns Telegram polling and reply delivery. The native plugin source at
`integrations/hermes_global_control/` intercepts only `/run`, `/tasks`, `/pause`,
and `/resume`, then forwards a normalized update once to the loopback endpoint.
Global Control still owns authorization, command parsing, routing, budget,
workers, and durable state. The adapter rejects non-loopback endpoint overrides
and never retries mutating commands automatically.

On Windows, `scripts/run_telegram_control.ps1` starts the local control endpoint
with an explicit Telegram user/chat allowlist and keeps runtime SQLite state
under `%LOCALAPPDATA%\xh-global-control\runtime` unless
`XH_CONTROL_RUNTIME_ROOT` is already set. The Hermes runtime plugin should link
to this repository directory so there is only one editable source.

Install the local endpoint as a limited-privilege Windows task with:

```powershell
.\scripts\install_telegram_autostart.ps1 -UserId <telegram-user-id> -ChatId <telegram-chat-id>
```

The installer starts it at logon and adds a one-minute watchdog trigger. It also
keeps the endpoint alive across battery and idle transitions; concurrent starts
are ignored.
