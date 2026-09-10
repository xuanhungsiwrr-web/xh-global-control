"""Transactional, versioned SQLite bootstrap."""

import sqlite3
from pathlib import Path

from xh_control.config import Configuration
from xh_control.exceptions import DatabaseInitializationError

LATEST_SCHEMA_VERSION = 2


def _apply_sql(connection: sqlite3.Connection, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    statement = ""
    for line in sql.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        raise DatabaseInitializationError(f"Incomplete SQL statement in {path.name}")


def initialize_database(config: Configuration) -> Path:
    """Initialize the configured database once, preserving existing rows."""
    path = config.database_path
    connection = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version < 0 or version > LATEST_SCHEMA_VERSION:
            raise DatabaseInitializationError("Database schema version is newer than this package supports")
        migrations = Path(__file__).parent / "migrations"
        for target_version in range(version + 1, LATEST_SCHEMA_VERSION + 1):
            matches = sorted(migrations.glob(f"{target_version:03d}_*.sql"))
            if len(matches) != 1:
                raise DatabaseInitializationError(
                    f"Expected exactly one migration for schema version {target_version}"
                )
            _apply_sql(connection, matches[0])
            connection.execute(f"PRAGMA user_version = {target_version}")
        connection.commit()
    except (OSError, sqlite3.Error) as exc:
        raise DatabaseInitializationError(f"Cannot initialize SQLite at {path} ({type(exc).__name__})") from None
    finally:
        if connection is not None:
            connection.close()
    return path
