import sqlite3

import pytest
from typer.testing import CliRunner

from xh_control.cli import app
from xh_control.config import load_config
from xh_control.exceptions import DatabaseInitializationError
from xh_control.state import initialize_database


def test_sqlite_initializes_idempotently(config_root):
    config = load_config(config_root)
    path = initialize_database(config)
    with sqlite3.connect(path) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert tables >= {"tasks", "execution_attempts", "task_events", "cost_events", "approvals", "artifacts", "channel_health", "global_learning_events"}
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        db.execute("INSERT INTO channel_health(channel_id,health,metadata_json) VALUES ('test','UNKNOWN','{}')")
        assert {row[1] for row in db.execute("PRAGMA table_info(execution_attempts)")} >= {"attempt_id", "attempt_no", "generation"}
        assert {row[1] for row in db.execute("PRAGMA table_info(tasks)")} >= {"assigned_worker_id", "latest_checkpoint_uri"}
    assert initialize_database(config) == path
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT channel_id FROM channel_health").fetchall() == [("test",)]
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_foreign_keys_and_append_only_events(config_root):
    path = initialize_database(load_config(config_root))
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO task_events(task_id,event_type,payload_json,created_at) VALUES ('missing','test','{}','now')")
        for table in ("execution_attempts", "task_events", "cost_events", "approvals", "artifacts", "global_learning_events"):
            assert db.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        columns = db.execute("PRAGMA table_info(tasks)").fetchall()
        required = [row[1] for row in columns if row[3] or row[5]]
        db.execute(f"INSERT INTO tasks ({','.join(required)}) VALUES ({','.join('?' for _ in required)})", ["T" if name == "task_id" else "0" for name in required])
        db.execute("INSERT INTO task_events(task_id,event_type,payload_json,created_at) VALUES ('T','test','{}','now')")
        for sql in ("UPDATE task_events SET event_type='changed'", "DELETE FROM task_events"):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                db.execute(sql)


def test_unknown_database_version_preserved(config_root):
    config = load_config(config_root)
    path = initialize_database(config)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version = 99")
    with pytest.raises(DatabaseInitializationError):
        initialize_database(config)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 99


def test_bootstrap_rolls_back_on_conflict(config_root):
    config = load_config(config_root)
    config.database_path.parent.mkdir()
    with sqlite3.connect(config.database_path) as db:
        db.execute("CREATE TABLE approvals(existing TEXT)")
    with pytest.raises(DatabaseInitializationError):
        initialize_database(config)
    with sqlite3.connect(config.database_path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("approvals",)]
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0


def test_cli_validate_config_succeeds(config_root):
    result = CliRunner().invoke(app, ["validate-config", "--config-root", str(config_root)])
    assert result.exit_code == 0, result.output
    assert "8 files" in result.output
    assert not load_config(config_root).database_path.exists()


def test_cli_validate_config_fails(config_root):
    (config_root / "workers.yaml").unlink()
    result = CliRunner().invoke(app, ["validate-config", "--config-root", str(config_root)])
    assert result.exit_code == 1
    assert "workers.yaml" in result.output


def test_cli_db_init_and_version(config_root):
    runner = CliRunner()
    for _ in range(2):
        result = runner.invoke(app, ["db-init", "--config-root", str(config_root)])
        assert result.exit_code == 0, result.output
    assert runner.invoke(app, ["version"]).output.strip() == "0.1.0"
