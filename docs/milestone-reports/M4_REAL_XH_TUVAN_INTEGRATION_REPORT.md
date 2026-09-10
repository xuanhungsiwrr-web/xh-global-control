# M4 Work Report

Historical report. For the authorized Option 1 implementation and current
acceptance status, see [M4 Option 1 report](M4_OPTION1_BRIDGE_REPORT.md).

## A. Milestone

```text
M4 — Real xh-tuvan integration
```

Branch: `ai/m4-xh-tuvan-integration`

Commit: none. The repository still has no commits; the M0-M3 baseline and the
user-owned `desktop.ini` remain untracked and preserved. No push or merge was
attempted.

## B. Status

```text
BLOCKED
```

The environment-independent M4 channel, worker, permission, artifact, cost, and
operational-metrics components are implemented and tested. The M4 exit criterion
is not met because the real installed `xh-tuvan` has no executable
TaskEnvelope/PluginResult bridge. No mock was used to claim completion.

## C. Files created

- `docs/architecture-change-requests/ACR-001.md`
- `docs/milestone-reports/M4_REAL_XH_TUVAN_INTEGRATION_REPORT.md`
- `src/xh_control/channels/factory.py`
- `src/xh_control/core/channel_execution_service.py`
- `src/xh_control/learning/__init__.py`
- `src/xh_control/learning/operational_metrics.py`
- `src/xh_control/models/learning.py`
- `src/xh_control/permissions/__init__.py`
- `src/xh_control/permissions/policy.py`
- `src/xh_control/workers/__init__.py`
- `src/xh_control/workers/selector.py`
- `tests/test_channel_execution_service.py`
- `tests/test_operational_metrics.py`
- `tests/test_permission_policy.py`
- `tests/test_worker_selector.py`

Runtime-only evidence (ignored by Git):

- `runtime/m4-channel-results/T-M4-CHANNEL-SMOKE-20260908/codex-subscription-5ffa1315aaa941c59a6a17c3d43521be.txt`
- `runtime/m4-real-evidence/control.db` (superseded development evidence)
- `runtime/m4-real-evidence/artifacts/7d3af0882a81ecebfcaeafe9/codex-subscription-a800ba06461c48aabc7c0295d2f7c5d9.txt` (superseded development evidence)
- `runtime/m4-real-evidence-v2/control.db`
- `runtime/m4-real-evidence-v2/artifacts/d69bed3d2fcc85b57ffe13bf/codex-subscription-534c542f4c8c4c6b8541be373c3d6084.txt`

The first persisted development run treated a provider cache counter as
additive. It was superseded after the service was corrected to persist only the
directly reported `input_tokens` value as context. Only the `v2` evidence below
is used for verification.

## D. Files modified

- `README.md`
- `config/plugins.yaml`
- `config/workers.yaml`
- `src/xh_control/channels/__init__.py`
- `src/xh_control/channels/_cli_health.py`
- `src/xh_control/channels/claude_code.py`
- `src/xh_control/channels/codex.py`
- `src/xh_control/core/__init__.py`
- `src/xh_control/exceptions.py`
- `src/xh_control/models/__init__.py`
- `src/xh_control/plugins/xh_tuvan_adapter.py`
- `src/xh_control/state/__init__.py`
- `src/xh_control/state/repositories.py`
- `tests/test_channel_adapters.py`
- `tests/test_plugin_contract.py`

No xh-tuvan plugin file, Hermes internal, Telegram handler, dashboard, failover,
or M6 resume implementation was modified.

## E. Tests run

Preflight:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\xhctl.exe validate-config
.\.venv\Scripts\python.exe -m pytest -q tests\integration\test_m3_subscription_routing.py
```

M4 component and final verification:

```powershell
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pytest -q tests\test_channel_execution_service.py tests\test_channel_adapters.py tests\test_permission_policy.py tests\test_operational_metrics.py tests\test_worker_selector.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\xhctl.exe validate-config
.\.venv\Scripts\python.exe -m pytest -q tests\integration\test_m3_subscription_routing.py tests\integration\test_m2_plugin_flow.py::test_generic_plugin_replaces_xh_tuvan_without_global_workflow_changes
```

Real environment and channel checks:

```powershell
codex login status
codex --version
codex exec --help
.\.venv\Scripts\python.exe -c $realPersistedChannelEvidenceScript
.\.venv\Scripts\python.exe -c $realXhTuvanProbeScript
```

The first Python command created a real read-only Codex subscription-channel
task/attempt in an isolated runtime workspace, invoked the actual CLI, and
persisted its output/artifact/cost/metrics/audit. The second checked the real
xh-tuvan manifest, Python module discovery, worker capability selection, and
adapter invocation; it intentionally exited non-zero on the verified bridge
blocker.

Security/boundary checks:

```powershell
rg -n -i <secret-patterns> src config tests README.md docs/architecture-change-requests
rg -n -i <domain-leak-patterns> src/xh_control/channels src/xh_control/core/channel_execution_service.py src/xh_control/learning src/xh_control/permissions src/xh_control/workers
git status --short --branch
```

## F. Test results

Preflight:

```text
pytest -q: exit 0; 129 passed, 0 failed, 0 skipped
xhctl validate-config: exit 0; 8 configuration files valid
M3 integration criterion: exit 0; 1 passed, 0 failed, 0 skipped
```

Final automated results:

```text
compileall: exit 0
M4 component selection: exit 0; 21 passed, 0 failed, 0 skipped
pytest -q: exit 0; 146 passed, 0 failed, 0 skipped
xhctl validate-config: exit 0; 8 configuration files valid
M3 + generic boundary selection: exit 0; 2 passed, 0 failed, 0 skipped
secret-pattern scan: exit 0; 0 hits
domain-leak scan in new Global modules: exit 0; 0 hits
```

Real execution-channel evidence:

```text
Codex CLI: codex-cli 0.153.4
Codex auth: exit 0; Logged in using ChatGPT
Execution channel: codex-subscription
Permission: SAFE_EDIT -> read-only project sandbox
Task: T-M4-REAL-CHANNEL-V2-20260909
Attempt: A-557B239B29154639, generation 1
Worker: pc-main
Channel execution: exit 0; success=true; latency=7.781 seconds
Output: XH_M4_PERSISTED_CHANNEL_V2_OK
Output bytes: 29
Output SHA-256: 88d010c29be10f0484f7834bff49839f7de0aa2f069fafad8d278819db8c99a8
Reported usage: input_tokens=14719, cached_input_tokens=5504, output_tokens=15
Persisted estimated_context_tokens: 14719 (cached tokens are not added, avoiding double count)
Persisted estimated_usd: 0.0; billing_mode=subscription
Workspace files created/modified by model: 0
```

Persisted records include task, attempt, resolved channel, worker, artifact
`AR-ACBFAC88C5284429`, cost event 1, operational event
`LE-97D89E7B557E402E`, and append-only audit events through
`CHANNEL_EXECUTION_FINISHED`. The generic smoke task remains `RUNNING` because no
fake PluginResult was created to finalize it.

Real xh-tuvan probe:

```text
Exit: 3 (blocked)
Plugin id: xh-tuvan
Version: 0.7.1
Installed type: Claude Desktop Local Agent skill bundle
Runtime id: plugin_013p78evpK7VKKaHAwA2vN8C
Configured Python module xh_tuvan: not found
Configured/actual xh-tuvan CLI: not found
Claude Code CLI: not found
Worker selection: pc-main missing claude_plugin_bridge
Adapter execution: PluginUnavailableError; see ACR-001
Plugin manifest SHA-256: 244e1b561a1b3edd49b2844a4b8e7614db3a6cfbc1e6c1848eddd0b1b74bc207
```

Installed plugin manifest path:

```text
C:\Users\xuanh\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\local-agent-mode-sessions\d5d55ab9-a8e2-4c7b-b1b7-34d18039f9aa\4f3dc124-b1a2-49e6-92a7-d2680143e291\rpm\plugin_013p78evpK7VKKaHAwA2vN8C\.claude-plugin\plugin.json
```

This is a transient Claude runtime cache path and is deliberately not hardcoded
as a production entry point. `config/plugins.yaml` records the stable runtime id
and actual version, plus the unsatisfied `claude_plugin_bridge` capability.

Claude Code execution is covered only by injected-runner unit tests on this host;
it was not presented as a real channel run. Codex was the only authenticated,
verified subscription execution channel.

## G. Exit criterion

BLOCKED.

`xhctl validate-config` passes with exit code 0, but M4 requires one real xh-tuvan
domain task end to end. That did not run. The real plugin is a skill bundle with
no TaskEnvelope input transport, no resolved-channel/permission/budget bridge,
and no PluginResult output transport. The real Codex smoke proves the independent
channel/persistence path only; it is not substituted for the plugin acceptance
test.

## H. Architecture deviations

`ACR-001` — PROPOSED: the installed xh-tuvan is a Claude Desktop skill bundle,
while the specification/config example expects a process entry point. A stable,
versioned bridge is required. The affected implementation stopped; no interface,
schema, ownership boundary, or Hermes internal was silently changed.

## I. Remaining issues

- Provide/approve an xh-tuvan-owned executable wrapper that accepts TaskEnvelope,
  receives an opaque resolved execution context, and returns PluginResult; or
  approve a formal Claude Desktop/Cowork skill-bundle runtime adapter.
- Provide a stable plugin installation path/runtime API. The discovered cache
  directory is not suitable as a production dependency.
- Install/authenticate Claude Code only if the chosen bridge requires it. Codex
  subscription execution is already verified, but Codex cannot be assumed to
  execute a Claude Desktop plugin bundle.
- After the bridge exists, run a small real domain task in an isolated workspace
  with explicit output criteria and reverify PluginResult, final task/attempt
  status, artifacts, cost, operational metrics, and audit.
- `XHTuvanAdapter` remains a guarded unavailable adapter, not a completed real
  bridge. Automated plugin tests remain mocks by design and are not M4 evidence.

## J. Next recommended milestone

```text
M5 — Telegram
```

Do not begin M5 until ACR-001 is decided and M4 is rerun to PASS. M5 was not
started.

STOP.
