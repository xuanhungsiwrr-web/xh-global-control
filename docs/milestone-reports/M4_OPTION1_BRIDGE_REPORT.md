# M4 — ACR-001 Option 1 work report

Date: 2026-09-09. Supersedes the bridge-availability blocker in the earlier
M4/M5 reports; does not claim their real-task or phone exit criteria passed.

## A. Milestone

M4 — plugin-owned xh-tuvan process bridge, ACR-001 Option 1, explicitly
authorized by the user. Branch: `ai/m4-xh-tuvan-bridge`.

Workspace: `D:/AI_Space_laptop/Global-control` (the actual on-disk path).
The repository has no commits; pre-existing files are untracked. They were
preserved, including `desktop.ini`. No commit, push, merge, or cache reinstall.
No AGENTS.md was found in the inspected workspace/ancestor/plugin paths.
Preflight baseline: 146 tests passed; config validation passed (8 files).

## B. Status

**PARTIAL — Option 1 implemented and real transport smoke COMPLETED.**

The prior missing-executable blocker is resolved. M4 cannot yet be marked
PASS: no user-selected real project workspace/task has been supplied. The live
assessment explicitly identified this repository as software, not a construction
project. A successful transport assessment is not domain acceptance.

## C. Files created

Paths relative to `D:/AI_Space_laptop/Global-control`:

- `src/xh_control/interfaces/__init__.py`
- `src/xh_control/interfaces/channel_bridge.py`
- `src/xh_control/interfaces/processes.py`
- `src/xh_control/interfaces/process_cli.py`
- `src/xh_control/plugins/process_adapter.py`
- `src/xh_control/plugins/factory.py`
- `src/xh_control/core/process_execution_service.py`
- `scripts/verify_m4_bridge.py`
- `tests/fixtures/process_plugin.py`
- `tests/test_process_bridge.py`
- `docs/milestone-reports/M4_OPTION1_BRIDGE_REPORT.md`

Plugin-owned files outside the Global repository:

- `C:/Users/xuanh/plugins/xh-tuvan/bridge/wrapper.py`
- `C:/Users/xuanh/plugins/xh-tuvan/bridge/PROTOCOL.md`
- `C:/Users/xuanh/plugins/xh-tuvan/bridge/test_wrapper.py`

Ignored local evidence directories:
`runtime/m4-bridge-live-smoke-20260909` and
`runtime/m4-bridge-live-smoke-v2-20260909` (task/result JSON, SQLite, artifacts).

## D. Files modified

Global-relative paths:

- `config/plugins.yaml`
- `src/xh_control/plugins/xh_tuvan_adapter.py`
- `src/xh_control/channels/_cli_health.py`
- `src/xh_control/channels/codex.py`
- `src/xh_control/core/channel_execution_service.py`
- `tests/test_worker_selector.py`
- `README.md`
- `docs/architecture-change-requests/ACR-001.md`
- `docs/IMPLEMENTATION_PROMPT_MVP_v0.1.md`
- `docs/milestone-reports/M4_REAL_XH_TUVAN_INTEGRATION_REPORT.md`
- `docs/milestone-reports/M5_TELEGRAM_REPORT.md`

Also `C:/Users/xuanh/plugins/xh-tuvan/README.md`: documents the separate bridge.
Existing plugin skills, manifest and desktop cache were not modified. Prompt
current authorization/default execution now reflect the latest M4 instruction;
common guardrails and historical M0 baseline requirements remain intact.

## E. Tests run

Final automated commands, all exit 0:

```powershell
# D:/AI_Space_laptop/Global-control
.\.venv\Scripts\python.exe -m pytest -q --tb=short
.\.venv\Scripts\xhctl.exe validate-config

# C:/Users/xuanh/plugins/xh-tuvan
D:/AI_Space_laptop/Global-control/.venv/Scripts/python.exe -m pytest -q tests bridge/test_wrapper.py --rootdir . --tb=short
```

Real smoke invocation, exit 0:

```powershell
.\.venv\Scripts\python.exe scripts/verify_m4_bridge.py --workspace D:/AI_Space_laptop/Global-control --request "Read-only transport smoke: use xh-tuvan to inspect README.md of this workspace and assess whether it supplies construction project inputs for the plugin. List actual missing prerequisites and next steps. The requested deliverable is this readiness assessment only. Do not create or modify project files, generate a report, call paid APIs, or treat this software repository as a real construction project. Clearly label the assessment as a smoke test, not M4 domain acceptance." --evidence-root runtime/m4-bridge-live-smoke-v2-20260909
```

Evidence-root creation is exclusive; use a new path for any rerun. Read-only
SQLite queries and `Get-FileHash` confirmed the evidence below (exit 0).

## F. Test results

- Global: **165 passed, 0 failed, 0 skipped**, 36.02 seconds; baseline 146,
  plus 19 process-bridge cases.
- Plugin: **10 passed, 0 failed, 0 skipped**, 1.26 seconds; existing 4 plus 6
  wrapper cases.
- Config: **valid, 8 files**, exit 0.
- Automated processes use fake channels and fixture artifacts, no LLM calls.
  Covered permission escalation (`test_permission_escalation_requires_approval`),
  duplicate task execution, task/context mismatch, unsupported request fields,
  fabricated usage/artifacts/result identities, missing domain gates, secret
  stderr isolation, timeout, cancellation ordering and generic plugin replacement.
  Windows asyncio self-pipe needs a narrowly scoped socketpair exemption; task
  network access remains blocked by the test fixture.
- Live smoke uses the actual plugin-owned wrapper, Codex subscription execution,
  real skill reads and artifact, not a fake channel. Task
  `T-M4-BRIDGE-A5148CCA33E8`: task and attempt **COMPLETED**; worker `pc-main`,
  channel `codex-subscription`, attempt 1, generation 1.
- Actual cost record: subscription; input tokens 89,839; output tokens 1,329;
  API estimated spend USD 0. This is not an assertion that the subscription
  itself is free. Plugin summary: 1 subscription call, 0 API calls, 0 retries,
  elapsed 74.657 seconds. Operational latency: 74.235 seconds.
- Two artifact registrations (`channel-output`, `plugin-deliverable`) point to
  one actual file, not two deliverables. SHA-256:
  `dd60d6c618a19ed2787f71acb8e7595d3126f05a91e031bd583cab7de45797b4`.
  File: `runtime/m4-bridge-live-smoke-v2-20260909/artifacts/ea2c33df01e3759b1042c95f/codex-subscription-457e762a88364e19bd3d191cbc4d1d2a.txt`.
- The first live smoke truthfully returned FAILED because Codex could not read
  files under its sandbox launch configuration. The tool reported nonzero exit
  1; no success is claimed. Its evidence is preserved separately. The second
  launch explicitly retained the host's Windows `elevated` sandbox implementation
  together with the task's read-only policy, without modifying user config or
  bypassing approval policy. [Official Windows sandbox documentation](https://learn.chatgpt.com/docs/windows/windows-sandbox).
- SQLite inspection showed operational events/metrics only, without domain
  assessment text or credentials. Domain content remains in the output artifact.

## G. Exit criterion

Config and automated checks PASS. Real **bridge** path PASS:
TaskEnvelope → task/attempt/worker/channel assignment → plugin process → scoped
channel bridge → real Codex execution → PluginResult/hash → cost/artifact/audit
records → terminal task and attempt.

M4 real **project/domain-task** acceptance remains **NOT MET**. No construction
project was invented or created. No phone, Telegram, Hermes end-to-end workflow,
safe pause/stop/checkpoint, handoff, restart or context-reuse acceptance is claimed.

Implemented local commands/interfaces:

- `python -m xh_control.interfaces.process_cli --envelope <absolute-task.json>`
  (optional `--config-root`); intended CLI exit 0 completed, 3 failure.
- `python scripts/verify_m4_bridge.py --workspace <authorized-project> --request <request> --evidence-root <new-directory>`.
- Plugin `wrapper.py --healthcheck` and `wrapper.py --context <transport-context>`.
- One-shot internal channel IPC client; no listener, HTTP endpoints, public
  deployment, dashboard or Telegram commands added in this M4 work.

## H. Architecture deviations

**ACR-001 Option 1 — approved and implemented.** No TaskEnvelope, PluginResult,
TaskStatus or DomainPluginAdapter signature changes; no Hermes internals edited.
Global owns routing, permissions, task/attempt fencing, costs and persistence.
Only the plugin-owned wrapper constructs domain instructions and evaluates its
domain output. Global validates generic contracts and hashes, not project facts.

Context is task-scoped and the authoritative fence/grant is revalidated before
and after channel execution. IPC files are transient transport, not authoritative
state. The local plugin is trusted same-user executable code, not an adversarial
plugin sandbox. Budgeted paid API execution is unavailable on this path.
Abort waits for owned execution termination; M4 failure handling does not
pretend to implement M5 safe-stop/CANCELLED semantics.

## I. Remaining issues

1. Need the user-selected real project path and a small authorized domain request
   to close M4. The pending request to the user is for a read-only readiness task;
   there is no need to grant unrestricted editing or paid API access.
2. Connector-dependent domain tasks cannot proceed in the isolated Codex path:
   user MCP/apps are excluded. Full report generation still requires the plugin's
   verified inputs, outline approval, templates, Gemini_QC and independent-review
   gates. Missing gates must produce blocked/FAILED, never substitute self-review.
3. Bridge lives in stable local plugin source outside this repository. Moving to
   another host requires deploying that source and changing the configured
   absolute entrypoint. Installed desktop cache is intentionally not the target.
4. M5 phone acceptance still requires user-designated test chat, usable Telegram
   credentials and Hermes integration. No recipient was guessed or contacted.

## J. Next recommended milestone

Complete the real-task evidence for **M4**, then **M5 — Telegram** under the
existing scoped request. Do not start M6 or failover. **STOP after this report.**
