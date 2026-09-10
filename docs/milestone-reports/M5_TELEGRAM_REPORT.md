# M5 Work Report

Latest review: [M5 Telegram review](M5_TELEGRAM_REVIEW_REPORT.md). ACR-001's
missing-bridge blocker is resolved; M4 real-project acceptance and M5
implementation/phone acceptance remain outstanding. Historical details below
must not be read as the current bridge state.

Historical M5 preflight. ACR-001 Option 1 was subsequently authorized as M4
work; see [current M4 report](M4_OPTION1_BRIDGE_REPORT.md). M5 remains gated on
real domain-task M4 acceptance, not merely bridge smoke success.

## A. Milestone

```text
M5 — Telegram
```

Branch: `ai/m5-telegram`

Commit: none. The repository still has no commits; the existing M0-M4 baseline
and the user-owned `desktop.ini` remain untracked and preserved. No push or
merge was attempted.

## B. Status

```text
BLOCKED
```

M5 implementation did not start because its mandatory M4 prerequisite is not
met. Direct inspection confirms that the only persisted M4 real-channel task is
a `generic-plugin` smoke task that remains `RUNNING`; it is not a real
`xh-tuvan` domain task. A follow-up review found personal Codex plugin
`xh-tuvan` 0.7.3 installed and enabled, and a fresh Codex process loaded its
skill successfully. The plugin is explicitly skills-only and supplies neither a
TaskEnvelope nor PluginResult bridge, so the configured real `XHTuvanAdapter`
still correctly reports unavailable pending ACR-001.

The Telegram/Hermes live prerequisite is also incomplete: Hermes Agent 0.21.0
is installed, but its gateway is not running, no Telegram configuration keys
were found in its local `.env`, and Global Control has no implemented
`InfrastructureAdapter` or `HermesInfrastructureAdapter` file.

Per the requested preflight stop rule, no Telegram command handler, Control API,
checkpoint/handoff behavior, test, config, or Implementation Prompt change was
made after these prerequisite failures were established.

## C. Files created

- `docs/milestone-reports/M5_TELEGRAM_REPORT.md`

## D. Files modified

- `docs/architecture-change-requests/ACR-001.md`
- `docs/milestone-reports/M5_TELEGRAM_REPORT.md`

In particular, `docs/IMPLEMENTATION_PROMPT_MVP_v0.1.md` was not changed because
preflight failed before implementation authorization could be applied.

## E. Tests run

```powershell
git switch -c ai/m5-telegram
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\xhctl.exe validate-config
```

Additional read-only verification:

```powershell
Get-Command hermes
hermes --version
hermes gateway status
hermes gateway list
Get-Command xh-tuvan,xh_tuvan,claude,codex
.\.venv\Scripts\python.exe -c <read-only M4 SQLite evidence query>
Get-FileHash runtime\m4-real-evidence-v2\artifacts\... -Algorithm SHA256
codex plugin list
codex exec --ephemeral --sandbox read-only -C <workspace> <plugin probe>
.\.venv\Scripts\python.exe -m pytest -q <xh-tuvan-plugin>\tests
.\.venv\Scripts\python.exe -m compileall -q <xh-tuvan-plugin>\scripts
```

Repository and installed Hermes source/config were inspected without printing
credential values. Only matching environment/config key presence was checked.

## F. Test results

```text
git switch -c ai/m5-telegram: exit 0
pytest -q: exit 0; 146 passed, 0 failed, 0 skipped
xhctl validate-config: exit 0; 8 configuration files valid
M5 automated tests: not run; no M5 implementation exists
M5 simulated Telegram evidence: none
M5 live/phone evidence: none
xh-tuvan plugin tests: exit 0; 4 passed, 0 failed, 0 skipped
xh-tuvan script compileall: exit 0
```

M4 evidence verification:

```text
Database: runtime/m4-real-evidence-v2/control.db
Task: T-M4-REAL-CHANNEL-V2-20260909
Plugin: generic-plugin
Task type: generic-channel-smoke
Status: RUNNING
Worker: pc-main
Channel: codex-subscription
Latest checkpoint: none
Artifact SHA-256: 88d010c29be10f0484f7834bff49839f7de0aa2f069fafad8d278819db8c99a8
xh_tuvan Python module: unavailable
xh-tuvan/xh_tuvan CLI: unavailable
XHTuvanAdapter healthcheck: hard-coded false pending ACR-001
xh-tuvan Codex plugin: installed and enabled, version 0.7.3
Fresh Codex plugin discovery: PASS
Runtime kind: skills-only
TaskEnvelope bridge: absent
PluginResult bridge: absent
```

This evidence proves a real Codex subscription-channel smoke only. It does not
satisfy the M4 exit criterion and is not represented as a real domain task.

Hermes/Telegram verification:

```text
Hermes Agent: 0.21.0 (2026.8.31)
Hermes command: installed
Gateway status: not running
Telegram-related keys in Hermes .env: none found
Global Hermes adapter implementation: absent
Configured/authorized test recipient: unavailable
Messages sent: 0
```

## G. Exit criterion

BLOCKED.

`xhctl validate-config` passes with exit code 0, but the M5 exit criterion is:

```text
The entire M4 workflow can be controlled from phone.
```

That criterion cannot be attempted truthfully while the M4 workflow itself is
blocked. No phone acceptance was simulated or inferred, and no recipient was
guessed.

Implemented M5 command surface:

```text
None
```

Implemented M5 Control API endpoints:

```text
None
```

## H. Architecture deviations

- `ACR-001` — PROPOSED: the installed Codex `xh-tuvan` 0.7.3 skills-only plugin
  has no approved executable TaskEnvelope/PluginResult bridge. The affected
  work remains stopped.

No Hermes internal was modified and no new ACR was required during this blocked
preflight.

## I. Remaining issues

- Resolve ACR-001 by providing/approving an executable bridge for the installed
  Codex `xh-tuvan` 0.7.3 skills-only plugin and a stable runtime API.
- Rerun one real `xh-tuvan` domain task end to end and update M4 to PASS.
- Implement the repository-owned `InfrastructureAdapter` and
  `HermesInfrastructureAdapter` boundary without importing Hermes internals into
  Global policy code.
- Configure Hermes Telegram credentials and the explicit controlling
  user/chat through secret-safe local configuration.
- Start the Hermes gateway for live verification.
- After prerequisites pass, update the Implementation Prompt from default M0
  authorization/instructions to M5-only authorization while preserving the
  shared guardrails.
- Implement and test the required commands: `/run`, `/status`, `/tasks`,
  `/master`, `/mode`, `/cost`, `/pause`, `/resume`, `/stop`, `/approve`, and
  `/deny`.
- Implement the thin local Control API using the same controller/services.
- Run fake-update/integration/security tests, including
  `test_permission_escalation_requires_approval`, duplicate/stale approval and
  wrong-task-ID coverage.
- Perform live acceptance only in the explicit user-designated test chat and
  record phone evidence separately from simulated evidence.

## J. Next recommended milestone

```text
M6 — Artifact-first resume
```

Do not begin M6. First resolve the M4 blocker and complete M5 with a passing
phone-controlled workflow.

STOP.
