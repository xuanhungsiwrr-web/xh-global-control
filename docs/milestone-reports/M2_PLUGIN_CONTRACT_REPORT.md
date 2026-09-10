# M2 Work Report

## A. Milestone

```text
M2 — Plugin contract
```

## B. Status

```text
PASS
```

Branch: `ai/m2-plugin-contract`

Commit: none. The repository has no commits yet and all M0/M1 baseline files were
already untracked, so no commit was created and no push or merge was attempted.

## C. Files created

- `src/xh_control/plugins/__init__.py`
- `src/xh_control/plugins/base.py`
- `src/xh_control/plugins/registry.py`
- `src/xh_control/plugins/xh_tuvan_adapter.py`
- `src/xh_control/core/plugin_execution_service.py`
- `tests/test_plugin_contract.py`
- `tests/integration/test_m2_plugin_flow.py`
- `docs/milestone-reports/M2_PLUGIN_CONTRACT_REPORT.md`

## D. Files modified

- `src/xh_control/exceptions.py`
- `src/xh_control/core/__init__.py`
- `README.md`

Unrelated baseline files, including the untracked `desktop.ini`, were preserved.

## E. Tests run

Prerequisite verification:

```powershell
. .\.venv\Scripts\Activate.ps1; pytest -q
. .\.venv\Scripts\Activate.ps1; xhctl validate-config
. .\.venv\Scripts\Activate.ps1; xhctl run --dry-run --plugin xh-tuvan --project M1-VERIFY --task "Opaque prerequisite verification" --task-type generate_report --task-id T-M1-VERIFY-20260908
.\.venv\Scripts\python.exe -c "import sqlite3,json; c=sqlite3.connect('runtime/control.db'); c.row_factory=sqlite3.Row; t=dict(c.execute('select task_id,plugin_id,task_type,status from tasks where task_id=?',('T-M1-VERIFY-20260908',)).fetchone()); e=[dict(r) for r in c.execute('select event_type,payload_json from task_events where task_id=? order by event_id',('T-M1-VERIFY-20260908',))]; print(json.dumps({'task':t,'events':e},ensure_ascii=False))"
```

M2 verification:

```powershell
. .\.venv\Scripts\Activate.ps1; python -m compileall -q src tests
. .\.venv\Scripts\Activate.ps1; pytest -q tests/test_plugin_contract.py tests/integration/test_m2_plugin_flow.py
. .\.venv\Scripts\Activate.ps1; pytest -q
. .\.venv\Scripts\Activate.ps1; xhctl validate-config
. .\.venv\Scripts\Activate.ps1; pytest -q tests/integration/test_m2_plugin_flow.py
```

## F. Test results

Final results:

```text
pytest -q: exit code 0; 102 passed, 0 failed, 0 skipped
xhctl validate-config: exit code 0; 8 configuration files valid
M2 integration test: exit code 0; 8 passed, 0 failed, 0 skipped
compileall: exit code 0
```

M1 prerequisite results:

```text
pytest -q: exit code 0; 91 passed, 0 failed, 0 skipped
xhctl validate-config: exit code 0
xhctl run --dry-run: exit code 0
SQLite evidence query: exit code 0
```

The first direct attempts to run `pytest -q` and `xhctl validate-config` without
activating `.venv` both returned exit code 1 because those executables were not
on `PATH`. Re-running the same commands in the repository virtual environment
passed. During development, the first M2-only run returned 2 passed and 9 failed
because the offline fixture blocks the loopback socket used by `asyncio.run()` on
Windows. The I/O-free mocks were changed to drive immediate coroutines without an
event loop; the rerun returned exit code 0 with 11 passed.

## G. Exit criterion

PASS. `test_mock_xh_tuvan_completes_and_persists_contract_state_and_audit`
demonstrates an offline mock `xh-tuvan` task reaching `COMPLETED`, with its opaque
artifact reference and audit trail persisted in SQLite. Global validates only the
plugin contract and operational summary; it contains no report workflow knowledge.

The critical boundary test
`test_generic_plugin_replaces_xh_tuvan_without_global_workflow_changes` also
passes using the same registry and execution service unchanged.

The M1 prerequisite dry-run persisted task `T-M1-VERIFY-20260908` with status
`CREATED` and one append-only `TASK_CREATED` event.

## H. Architecture deviations

None. No ACR was required.

## I. Remaining issues

None within M2 scope.

Real plugin execution, subscription routing, Telegram, and restart resume remain
intentionally unimplemented because they belong to later authorized milestones.

## J. Next recommended milestone

```text
M3 — Subscription router
```

M3 was not started.
