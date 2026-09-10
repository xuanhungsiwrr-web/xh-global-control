# M3 Work Report

## A. Milestone

```text
M3 — Subscription router
```

Branch: `ai/m3-subscription-router`

Commit: none. The repository still has no commits; the M0–M2 baseline and the
user-owned `desktop.ini` remain untracked and preserved. No push or merge was
attempted.

## B. Status

```text
PASS
```

## C. Files created

- `src/xh_control/channels/__init__.py`
- `src/xh_control/channels/base.py`
- `src/xh_control/channels/_cli_health.py`
- `src/xh_control/channels/claude_code.py`
- `src/xh_control/channels/codex.py`
- `src/xh_control/routing/__init__.py`
- `src/xh_control/routing/channel_router.py`
- `src/xh_control/routing/master_selector.py`
- `src/xh_control/models/budget.py`
- `src/xh_control/models/channel_health.py`
- `src/xh_control/core/budget_engine.py`
- `tests/test_channel_adapters.py`
- `tests/test_subscription_router.py`
- `tests/test_budget_engine.py`
- `tests/integration/test_m3_subscription_routing.py`
- `docs/milestone-reports/M3_SUBSCRIPTION_ROUTER_REPORT.md`

## D. Files modified

- `README.md`
- `src/xh_control/exceptions.py`
- `src/xh_control/core/__init__.py`
- `src/xh_control/core/identifiers.py`
- `src/xh_control/models/__init__.py`
- `src/xh_control/models/execution.py`
- `src/xh_control/state/__init__.py`
- `src/xh_control/state/repositories.py`

No configuration file, Hermes internal, plugin domain workflow, Telegram,
dashboard, failover, or distributed-infrastructure implementation was changed.

## E. Tests run

Pre-implementation prerequisite verification:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\integration\test_m2_plugin_flow.py -k "mock_xh_tuvan_completes_and_persists_contract_state_and_audit or generic_plugin_replaces_xh_tuvan_without_global_workflow_changes"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\xhctl.exe validate-config
```

M3 verification:

```powershell
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pytest -q tests\test_channel_adapters.py tests\test_subscription_router.py tests\test_budget_engine.py tests\integration\test_m3_subscription_routing.py
.\.venv\Scripts\python.exe -m pytest -q tests\test_subscription_router.py::test_subscription_channel_beats_api_when_capable tests\test_subscription_router.py::test_unhealthy_subscription_is_skipped tests\test_budget_engine.py::test_hard_budget_requires_approval
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\xhctl.exe validate-config
```

Real environment checks, separate from simulated pytest health:

```powershell
$c = Get-Command claude -ErrorAction SilentlyContinue; if ($null -eq $c) { 'CLAUDE_CLI=NOT_FOUND'; exit 0 }; "CLAUDE_CLI=$($c.Source)"; claude auth --help
$c = Get-Command codex -ErrorAction SilentlyContinue; if ($null -eq $c) { 'CODEX_CLI=NOT_FOUND'; exit 0 }; "CODEX_CLI=$($c.Source)"; codex login --help
$healthProbe = @'
import asyncio
import json
from xh_control.channels import ClaudeCodeAdapter, CodexAdapter

async def main():
    result = {
        "claude": await ClaudeCodeAdapter().healthcheck(),
        "codex": await CodexAdapter().healthcheck(),
    }
    print(json.dumps(result, sort_keys=True))

asyncio.run(main())
'@
.\.venv\Scripts\python.exe -c $healthProbe
```

The adapter probe called only `claude auth status --json` and `codex login status`
with stdin closed. Claude stdout is parsed transiently for `loggedIn` only; raw
stdout and all stderr are never returned or persisted. It did not start an LLM
completion.

## F. Test results

Prerequisites:

```text
M2 mock completion + generic boundary: exit 0; 2 passed, 6 deselected
Baseline pytest -q: exit 0; 102 passed, 0 failed, 0 skipped
Baseline xhctl validate-config: exit 0; 8 configuration files valid
```

Final M3 results:

```text
compileall: exit 0
M3 acceptance/unit selection: exit 0; 27 passed, 0 failed, 0 skipped
three mandatory named tests: exit 0; 3 passed, 0 failed, 0 skipped
pytest -q: exit 0; 129 passed, 0 failed, 0 skipped
xhctl validate-config: exit 0; 8 configuration files valid
secret-pattern scope scan: exit 0; 0 hits
domain-leak scope scan: exit 0; 0 hits
```

Real health evidence:

```text
Claude CLI discovery: CLI_NOT_FOUND
ClaudeCodeAdapter: UNAVAILABLE / CLI_NOT_FOUND / quota_checked=false
Codex CLI help: exit 0; `login status` is supported
CodexAdapter: AVAILABLE / CLI_AUTHENTICATED / quota_checked=false
combined adapter probe: exit 0
```

The real probe does not claim API or subscription quota. Automated tests use
injected command results and explicit per-channel health records; these are
simulation, not evidence about the host subscriptions.

## G. Exit criterion

PASS.

`xhctl validate-config` passes with exit code 0.

`test_both_healthy_subscriptions_prevent_paid_api_selection` persists simulated
`AVAILABLE` health for both subscription channel IDs, adds an extremely
high-scored/high-priority premium API candidate, and still selects a subscription
with zero cost events and zero approvals. This proves the M3 criterion: when both
subscription channels are healthy and capable, no paid API is selected.

Routing evidence also covers the exact hard class order, capability/enablement
filtering, unavailable and rate-limit cooldown filtering, model-specific health,
UNKNOWN reliability treatment, deterministic handoff penalty, logical Master
preference/fallback, cross-provider policy, all three cost modes, and no eligible
channel.

Budget evidence covers exact soft/hard edges, task/daily/global-monthly scopes,
persisted actual cost and audit, atomic `EXCEED_API_HARD_LIMIT` approval plus
`WAITING_APPROVAL`, and continued authorization of subscription/local actions
while the independent paid action remains blocked. No paid API execution was
implemented.

## H. Architecture deviations

None. No ACR was required. Budget scopes are evaluated independently: crossing
any configured hard scope blocks that paid action; crossing any task/daily soft
scope warns. Task plugin/default limits are resolved into `TaskEnvelope` at intake,
as in the existing implementation, while daily and global-monthly limits are read
directly by `BudgetEngine`.

## I. Remaining issues

- The current host does not have the Claude CLI, so real dual-subscription healthy
  state cannot be observed here. This is an environment condition, not a failed
  simulated acceptance criterion.
- No `AGENTS.md` exists in the workspace or its parent `D:\AI_Space_laptop`; the
  complete Specification and Implementation Prompt therefore supplied the active
  repository guardrails.

## J. Next recommended milestone

```text
M4 — Real xh-tuvan integration
```

M4 was not started.

STOP.
