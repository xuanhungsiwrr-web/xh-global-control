import sqlite3

from typer.testing import CliRunner

from xh_control.cli import app
from xh_control.config import load_config


def test_cli_dry_run_creates_task_and_audit_trail(config_root):
    result = CliRunner().invoke(
        app,
        [
            "run",
            "--dry-run",
            "--plugin",
            "xh-tuvan",
            "--project",
            "PROJECT-X",
            "--task",
            "opaque request",
            "--task-id",
            "T-CLI-1",
            "--config-root",
            str(config_root),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Task created: T-CLI-1" in result.output
    assert "Status: CREATED" in result.output
    assert "Audit events: 1" in result.output
    with sqlite3.connect(load_config(config_root).database_path) as connection:
        assert connection.execute("SELECT status FROM tasks").fetchall() == [("CREATED",)]
        assert connection.execute("SELECT event_type FROM task_events").fetchall() == [
            ("TASK_CREATED",)
        ]


def test_cli_rejects_execution_and_malformed_or_duplicate_tasks(config_root):
    runner = CliRunner()
    base = [
        "run",
        "--plugin",
        "generic-plugin",
        "--project",
        "P",
        "--task",
        "request",
        "--task-id",
        "T-DUPLICATE",
        "--config-root",
        str(config_root),
    ]
    result = runner.invoke(app, base)
    assert result.exit_code == 2
    assert "only with --dry-run" in result.output
    assert runner.invoke(app, base + ["--dry-run"]).exit_code == 0
    duplicate = runner.invoke(app, base + ["--dry-run"])
    assert duplicate.exit_code == 1
    assert "Task already exists" in duplicate.output


def test_schema_one_database_is_migrated_to_m1(config_root):
    config = load_config(config_root)
    first = CliRunner().invoke(app, ["db-init", "--config-root", str(config_root)])
    assert first.exit_code == 0
    with sqlite3.connect(config.database_path) as connection:
        connection.execute("DROP INDEX execution_attempts_task_attempt_no")
        connection.execute("DROP INDEX execution_attempts_task_generation")
        connection.execute("DROP INDEX task_events_task_event")
        connection.execute("DROP INDEX artifacts_task_created")
        connection.execute("DROP TRIGGER execution_attempts_positive_insert")
        connection.execute("DROP TRIGGER execution_attempts_positive_update")
        connection.execute("PRAGMA user_version = 1")
    second = CliRunner().invoke(app, ["db-init", "--config-root", str(config_root)])
    assert second.exit_code == 0, second.output
    with sqlite3.connect(config.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (2,)
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='execution_attempts_task_generation'"
        ).fetchone() == (1,)
