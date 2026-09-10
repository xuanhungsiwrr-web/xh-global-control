# M6 Artifact-first resume and MVP v0.1 acceptance report — 2026-09-09

## A. Milestone

```text
M6 — Artifact-first resume and final MVP v0.1 acceptance
```

Authorized scope was M6 and final MVP acceptance only. No post-MVP work,
deployment, push, merge, distributed lease/lock, heartbeat daemon, or automatic
PC-to-laptop failover was authorized or performed.

Branch: `ai/m6-artifact-resume`

The repository has no commits. All pre-existing untracked files, including
`desktop.ini`, were preserved.

## B. Status

```text
BLOCKED
```

M6 implementation did not start because the explicit prerequisite, M5 phone
control acceptance, is not met. This is confirmed by current source and live
readiness checks, not merely inferred from an older report:

- the source tree contains no Telegram adapter/handler, Hermes infrastructure
  adapter, Control API, or `GlobalController` implementation;
- the required M5 command surface has no Telegram implementation;
- Hermes Agent 0.21.0 is installed, but `hermes gateway status` reports that the
  gateway is not running;
- the configured Google Drive project root `G:/My Drive/Projects` does not exist
  in this environment;
- Codex CLI is present, but Claude CLI is absent, so two healthy subscription
  channels cannot be established;
- the latest M5 review records 0/11 implemented commands and no live/phone
  acceptance evidence;
- plugin `pause`/`resume` methods are interface/adapter placeholders rather than
  a completed M5 safe checkpoint/handoff implementation.

Per the user's preflight rule, a missing prerequisite requires evidence and a
BLOCKED result. Therefore no M6 source, schema, config, test, or Implementation
Prompt change was made. In particular, the stale M4 authorization/default
execution instruction in `docs/IMPLEMENTATION_PROMPT_MVP_v0.1.md` was not
changed after the gate failed.

`AGENTS.md` was searched for in the workspace and its ancestors but was not
present. The complete Implementation Spec, complete Implementation Prompt, and
both M5 reports were read.

## C. Files created

- `docs/milestone-reports/M6_ARTIFACT_RESUME_MVP_ACCEPTANCE_REPORT.md`

No M6 implementation artifacts were created.

## D. Files modified

None.

## E. Tests run

From `D:/AI_Space_laptop/Global-control`:

```powershell
git switch -c ai/m6-artifact-resume
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\xhctl.exe validate-config
hermes --version
hermes gateway status
```

Additional read-only checks covered Git/workspace writability, current branch,
the M5/M6 implementation surface, required tests, configured defaults, command
availability, and the configured Google Drive project root. A temporary write
probe under ignored `runtime/` succeeded and was removed immediately.

## F. Test results

| Command/check | Exit/result | Evidence class |
|---|---:|---|
| `git switch -c ai/m6-artifact-resume` | 0 | Real local Git |
| workspace write probe | success; probe removed | Real local filesystem |
| `pytest -q` | 0; 165 passed, 0 failed, 0 skipped | Automated/offline |
| `xhctl validate-config` | 0; 8 files valid | Automated/offline |
| `hermes --version` | 0; Hermes Agent 0.21.0 | Real local install |
| `hermes gateway status` | diagnostic ran; gateway **not running** | Real live readiness failure |
| Telegram command implementation | 0/11 | Current source inspection |
| M5 phone acceptance | none | No real evidence |
| `test_artifact_hashing` | absent | Current test inspection |
| configured project root | `G:/My Drive/Projects` absent | Real filesystem check |
| Codex CLI | present | Real local install |
| Claude CLI | absent | Real local readiness failure |

The 165 passing tests establish the M0-M4 automated baseline only. They do not
constitute M5 phone acceptance or M6 controller-restart acceptance.

## G. Exit criterion

### M6

Not met and not attempted. The required criterion is:

```text
Stop/restart Global Control and resume an interrupted task without replaying
the full chat history.
```

There is currently no runnable Global controller to stop/restart, no completed
M5 safe checkpoint/resume flow, and no M6 checkpoint persistence/reload layer.

### Final MVP v0.1 readiness

| Given condition from Spec section 34 | Status | Real evidence |
|---|---|---|
| PC online | PARTIAL | This local shell is online; configured `pc-main` execution health was not established through a controller. |
| Hermes online | FAIL | Gateway reports not running. |
| Telegram connected | NOT VERIFIED | No Global Telegram implementation or phone acceptance evidence. |
| Claude subscription healthy | FAIL/NOT VERIFIED | Claude CLI is absent. |
| Codex subscription healthy | NOT VERIFIED LIVE | CLI is present; no current two-channel health run through Global. |
| `xh-tuvan` registered | CONFIG ONLY | Present in `config/plugins.yaml`; not sufficient for live acceptance. |
| project available on Google Drive | FAIL | Configured `G:/My Drive/Projects` path is absent. |
| default mode BALANCED | PASS | `config/system.yaml` sets `default_cost_mode: BALANCED`. |

Because the Given conditions are not satisfied, no `/run` message was sent and
no test project or Telegram recipient was invented.

### Twelve acceptance criteria

`PASS` below is reserved for evidence from the required live scenario. Unit,
mock, configuration, and prior smoke evidence is listed separately and is not
promoted to live PASS.

| # | Criterion | Live status | Existing non-live evidence |
|---:|---|---|---|
| 1 | Global creates `TaskEnvelope` | NOT RUN | Model/unit coverage exists. |
| 2 | Global validates permission and budget | NOT RUN | Offline permission/budget tests pass. |
| 3 | Global assigns `pc-main` | NOT RUN | Worker config and selector tests exist. |
| 4 | MASTER uses subscription-first routing | NOT RUN | Router tests pass with mocks/config. |
| 5 | No API when subscription is sufficient | NOT RUN | Automated routing tests cover policy only. |
| 6 | Global calls `XHTuvanAdapter` | NOT RUN | M4 bridge smoke/contract evidence exists; no M5 live scenario. |
| 7 | Plugin owns its internal workflow | NOT RUN | Boundary/contract tests exist; no live scenario. |
| 8 | Plugin returns output/status/operational learning | NOT RUN | M4 contract evidence exists; no live scenario. |
| 9 | Global stores audit/cost/checkpoint | NOT RUN | M0-M4 repositories exist; M6 global checkpoint does not. |
| 10 | Telegram returns completion/status | NOT RUN | Telegram implementation and phone evidence are absent. |
| 11 | Global stores no domain knowledge | NOT RUN | Automated generic-plugin/learning-boundary tests exist. |
| 12 | Resume from artifacts after controller restart | NOT RUN | M6 implementation and real restart test are absent. |

Final MVP v0.1 acceptance is therefore **BLOCKED**, independently of the fact
that the baseline offline suite passes.

### M6 plan after prerequisites are satisfied

The scoped plan derived from Spec sections 13, 16, 18, 26, 29-30, and 34 is:

1. Add the Global project layout `GLOBAL_TASK.json`, `STATE.json`,
   `HANDOFF.json`, `ARTIFACT_INDEX.json`, and numbered checkpoints using the
   specified fields. Treat `plugin_state_ref` as opaque and do not create a
   second Global domain-decisions store by default.
2. Implement deterministic SHA-256, artifact accessibility/path checks, and
   atomic checkpoint writes. Update SQLite `latest_checkpoint_uri` only after
   the checkpoint and all required references have been persisted successfully.
3. Restore from SQLite as runtime authority, validate task identity/schema/hash,
   retain task identity, and manage attempt/generation using the existing
   contract. Keep `/stop` terminal `CANCELLED`, distinct from controller
   interruption.
4. Reconcile the previous worker/plugin execution state before restarting work,
   preventing duplicate execution and refusing blind replay of uncertain
   external side effects.
5. Pass accessible references instead of chat content, reuse immutable artifacts
   only when both hash and destination accessibility are confirmed, and reuse
   the existing router handoff penalty.
6. Add hashing, persist/reload, actual process restart, corruption/missing/hash/
   wrong-task/incompatible-checkpoint, interrupted-write, repeated-resume,
   no-duplicate, no-transcript, and generic-plugin boundary tests.
7. Run the live section 34 scenario and record real evidence separately from
   mock/offline evidence.

This plan was not executed after the M5 gate failed.

## H. Architecture deviations

None. No Architecture Change Request was needed because the blockers are missing
prerequisite implementation/environment evidence, not a conflict with the
architecture. ACR-001 remains the previously approved M4 bridge decision.

## I. Remaining issues

1. Complete and genuinely accept M5: implement the thin Telegram/Hermes/control
   boundary and demonstrate the full M4 workflow from the user's phone.
2. Start Hermes gateway and configure an explicitly authorized Telegram test
   chat using excluded secret storage.
3. Make both subscription channels healthy and verify them through Global.
4. Mount/provide an explicitly selected real Google Drive test project.
5. Re-run M6 authorization after the prerequisite is met; then update the
   Implementation Prompt to M6-only authorization and its default execution
   instruction before coding.
6. Implement and verify M6 according to the scoped plan above.
7. Run the real `/run` acceptance scenario and collect all 12 evidence items.

## J. Next recommended milestone

M6 remains the next milestone, but it is gated on real M5 phone acceptance.
MVP v0.1 may be declared complete only after M6 and all 12 live acceptance
criteria have real evidence. Every v0.2 or post-MVP extension requires separate
authorization.

STOP.
