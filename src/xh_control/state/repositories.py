"""SQLite repositories for M1 task, attempt, event, and artifact state."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Iterator

from xh_control.exceptions import (
    ArtifactNotFoundError,
    AttemptNotFoundError,
    DuplicateRecordError,
    InvalidGenerationError,
    StateConflictError,
    TaskNotFoundError,
)
from xh_control.models import (
    ApprovalRecord,
    ApprovalStatus,
    ArtifactRecord,
    ChannelHealthRecord,
    CostEventRecord,
    ExecutionAttemptRecord,
    FailureType,
    GlobalLearningEventRecord,
    TaskEnvelope,
    TaskEventRecord,
    TaskRecord,
    TaskStatus,
)


def _timestamp(value: datetime) -> str:
    return value.isoformat()


def _payload(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class SQLiteRepository:
    """Own short-lived SQLite connections and transaction setup."""

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def validate_task_attempt_refs(
        connection: sqlite3.Connection,
        task_id: str,
        attempt_id: str | None,
    ) -> None:
        task = connection.execute(
            "SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if task is None:
            raise TaskNotFoundError(f"Task not found: {task_id}")
        if attempt_id is not None:
            attempt = connection.execute(
                "SELECT task_id FROM execution_attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
            if attempt is None:
                raise AttemptNotFoundError(f"Attempt not found: {attempt_id}")
            if attempt["task_id"] != task_id:
                raise StateConflictError(
                    f"Attempt {attempt_id} does not belong to task {task_id}"
                )


class TaskRepository(SQLiteRepository):
    """Persist task records and task-coupled attempt changes."""

    def create(self, task: TaskEnvelope, created_at: datetime) -> TaskRecord:
        values = (
            task.task_id,
            task.schema_version,
            task.plugin,
            task.task_type,
            task.report_type,
            task.project.project_id,
            task.project.workspace_uri,
            task.user_request,
            task.execution.cost_mode.value,
            task.execution.master_preference.value,
            task.permissions.level.value,
            task.budget.api_soft_usd,
            task.budget.api_hard_usd,
            TaskStatus.CREATED.value,
            _timestamp(task.created_at),
            _timestamp(created_at),
        )
        try:
            with self.connection() as connection, connection:
                connection.execute(
                    """
                    INSERT INTO tasks (
                        task_id, schema_version, plugin_id, task_type, report_type,
                        project_id, workspace_uri, user_request, cost_mode,
                        master_preference, permission_level, api_soft_usd,
                        api_hard_usd, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                self._append_event(
                    connection,
                    task.task_id,
                    None,
                    "TASK_CREATED",
                    {"status": TaskStatus.CREATED.value},
                    created_at,
                )
        except sqlite3.IntegrityError:
            raise DuplicateRecordError(f"Task already exists: {task.task_id}") from None
        return self.get(task.task_id)

    def get(self, task_id: str) -> TaskRecord:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise TaskNotFoundError(f"Task not found: {task_id}")
        return self._task_record(row)

    def list(self, limit: int = 100) -> list[TaskRecord]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks ORDER BY created_at, task_id LIMIT ?", (limit,)
            ).fetchall()
        return [self._task_record(row) for row in rows]

    def transition(
        self,
        task_id: str,
        expected: TaskStatus,
        target: TaskStatus,
        changed_at: datetime,
        *,
        attempt_id: str | None = None,
        generation: int | None = None,
    ) -> TaskRecord:
        with self.connection() as connection, connection:
            if attempt_id is None:
                result = connection.execute(
                    "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ? AND status = ?",
                    (target.value, _timestamp(changed_at), task_id, expected.value),
                )
            else:
                result = connection.execute(
                    """
                    UPDATE tasks SET status = ?, updated_at = ?
                    WHERE task_id = ? AND status = ? AND current_attempt_id = ?
                      AND EXISTS (
                          SELECT 1 FROM execution_attempts
                          WHERE attempt_id = ? AND task_id = tasks.task_id AND generation = ?
                      )
                    """,
                    (
                        target.value,
                        _timestamp(changed_at),
                        task_id,
                        expected.value,
                        attempt_id,
                        attempt_id,
                        generation,
                    ),
                )
            if result.rowcount != 1:
                row = connection.execute(
                    "SELECT status FROM tasks WHERE task_id = ?", (task_id,)
                ).fetchone()
                if row is None:
                    raise TaskNotFoundError(f"Task not found: {task_id}")
                raise StateConflictError(
                    f"Task {task_id} changed from expected status {expected.value}"
                )
            self._append_event(
                connection,
                task_id,
                attempt_id,
                "TASK_STATUS_CHANGED",
                {"from_status": expected.value, "to_status": target.value},
                changed_at,
            )
        return self.get(task_id)

    def create_attempt(
        self,
        task_id: str,
        attempt_id: str,
        worker_id: str,
        channel_id: str | None,
        created_at: datetime,
        generation: int | None = None,
    ) -> ExecutionAttemptRecord:
        with self.connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            task = connection.execute(
                "SELECT task_id FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task is None:
                raise TaskNotFoundError(f"Task not found: {task_id}")
            sequence = connection.execute(
                """
                SELECT COALESCE(MAX(attempt_no), 0) + 1,
                       COALESCE(MAX(generation), 0) + 1
                FROM execution_attempts WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
            attempt_no = int(sequence[0])
            required_generation = int(sequence[1])
            selected_generation = required_generation if generation is None else generation
            if selected_generation != required_generation:
                raise InvalidGenerationError(
                    f"Task {task_id} requires generation {required_generation}, got {selected_generation}"
                )
            try:
                connection.execute(
                    """
                    INSERT INTO execution_attempts (
                        attempt_id, task_id, attempt_no, worker_id, channel_id,
                        status, generation
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        attempt_id,
                        task_id,
                        attempt_no,
                        worker_id,
                        channel_id,
                        TaskStatus.ASSIGNED.value,
                        selected_generation,
                    ),
                )
            except sqlite3.IntegrityError:
                raise DuplicateRecordError(f"Attempt already exists: {attempt_id}") from None
            connection.execute(
                """
                UPDATE tasks SET assigned_worker_id = ?, resolved_channel_id = ?,
                    current_attempt_id = ?, updated_at = ? WHERE task_id = ?
                """,
                (worker_id, channel_id, attempt_id, _timestamp(created_at), task_id),
            )
            self._append_event(
                connection,
                task_id,
                attempt_id,
                "ATTEMPT_CREATED",
                {
                    "attempt_id": attempt_id,
                    "attempt_no": attempt_no,
                    "generation": selected_generation,
                    "worker_id": worker_id,
                    "channel_id": channel_id,
                },
                created_at,
            )
        return self.get_attempt(attempt_id)

    def get_attempt(self, attempt_id: str) -> ExecutionAttemptRecord:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM execution_attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
        if row is None:
            raise AttemptNotFoundError(f"Attempt not found: {attempt_id}")
        return self._attempt_record(row)

    def list_attempts(self, task_id: str) -> list[ExecutionAttemptRecord]:
        self.get(task_id)
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM execution_attempts WHERE task_id = ? ORDER BY attempt_no",
                (task_id,),
            ).fetchall()
        return [self._attempt_record(row) for row in rows]

    def transition_attempt(
        self,
        task_id: str,
        attempt_id: str,
        generation: int,
        expected: TaskStatus,
        target: TaskStatus,
        changed_at: datetime,
        *,
        failure_type: FailureType | None = None,
        failure_message: str | None = None,
    ) -> ExecutionAttemptRecord:
        terminal = target in {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
        with self.connection() as connection, connection:
            result = connection.execute(
                """
                UPDATE execution_attempts
                SET status = ?,
                    started_at = CASE
                        WHEN ? = 'RUNNING' AND started_at IS NULL THEN ?
                        ELSE started_at
                    END,
                    ended_at = CASE WHEN ? THEN ? ELSE ended_at END,
                    failure_type = ?,
                    failure_message = ?
                WHERE attempt_id = ? AND task_id = ? AND generation = ? AND status = ?
                  AND EXISTS (
                      SELECT 1 FROM tasks
                      WHERE tasks.task_id = execution_attempts.task_id
                        AND tasks.current_attempt_id = execution_attempts.attempt_id
                  )
                """,
                (
                    target.value,
                    target.value,
                    _timestamp(changed_at),
                    terminal,
                    _timestamp(changed_at),
                    failure_type.value if failure_type else None,
                    failure_message,
                    attempt_id,
                    task_id,
                    generation,
                    expected.value,
                ),
            )
            if result.rowcount != 1:
                row = connection.execute(
                    "SELECT 1 FROM execution_attempts WHERE attempt_id = ?", (attempt_id,)
                ).fetchone()
                if row is None:
                    raise AttemptNotFoundError(f"Attempt not found: {attempt_id}")
                raise StateConflictError(
                    f"Attempt {attempt_id} changed or is no longer current for task {task_id}"
                )
            self._append_event(
                connection,
                task_id,
                attempt_id,
                "ATTEMPT_STATUS_CHANGED",
                {
                    "attempt_id": attempt_id,
                    "from_status": expected.value,
                    "to_status": target.value,
                    "generation": generation,
                    "failure_type": failure_type.value if failure_type else None,
                },
                changed_at,
            )
        return self.get_attempt(attempt_id)

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        task_id: str,
        attempt_id: str | None,
        event_type: str,
        payload: dict,
        created_at: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO task_events(task_id, attempt_id, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (task_id, attempt_id, event_type, _payload(payload), _timestamp(created_at)),
        )

    @staticmethod
    def _task_record(row: sqlite3.Row) -> TaskRecord:
        envelope = TaskEnvelope.model_validate(
            {
                "schema_version": row["schema_version"],
                "task_id": row["task_id"],
                "created_at": row["created_at"],
                "task_type": row["task_type"],
                "plugin": row["plugin_id"],
                "report_type": row["report_type"],
                "project": {
                    "project_id": row["project_id"],
                    "workspace_uri": row["workspace_uri"],
                },
                "execution": {
                    "master_capability": "MASTER",
                    "master_preference": row["master_preference"],
                    "cost_mode": row["cost_mode"],
                },
                "permissions": {"level": row["permission_level"]},
                "budget": {
                    "api_soft_usd": row["api_soft_usd"],
                    "api_hard_usd": row["api_hard_usd"],
                },
                "user_request": row["user_request"],
            }
        )
        return TaskRecord(
            task=envelope,
            status=row["status"],
            assigned_worker=row["assigned_worker_id"],
            resolved_channel=row["resolved_channel_id"],
            current_attempt_id=row["current_attempt_id"],
            latest_checkpoint_uri=row["latest_checkpoint_uri"],
        )

    @staticmethod
    def _attempt_record(row: sqlite3.Row) -> ExecutionAttemptRecord:
        return ExecutionAttemptRecord.model_validate(dict(row))


class EventRepository(SQLiteRepository):
    """Append and read immutable audit events."""

    def append(
        self,
        task_id: str,
        event_type: str,
        payload: dict,
        created_at: datetime,
        attempt_id: str | None = None,
    ) -> TaskEventRecord:
        with self.connection() as connection, connection:
            self.validate_task_attempt_refs(connection, task_id, attempt_id)
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO task_events(task_id, attempt_id, event_type, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (task_id, attempt_id, event_type, _payload(payload), _timestamp(created_at)),
                )
                event_id = int(cursor.lastrowid)
            except sqlite3.IntegrityError:
                raise StateConflictError(
                    f"Could not append event for task {task_id}"
                ) from None
        return self.get(event_id)

    def get(self, event_id: int) -> TaskEventRecord:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM task_events WHERE event_id = ?", (event_id,)
            ).fetchone()
        if row is None:
            raise TaskNotFoundError(f"Task event not found: {event_id}")
        return self._event_record(row)

    def list_for_task(self, task_id: str) -> list[TaskEventRecord]:
        with self.connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if exists is None:
                raise TaskNotFoundError(f"Task not found: {task_id}")
            rows = connection.execute(
                "SELECT * FROM task_events WHERE task_id = ? ORDER BY event_id", (task_id,)
            ).fetchall()
        return [self._event_record(row) for row in rows]

    @staticmethod
    def _event_record(row: sqlite3.Row) -> TaskEventRecord:
        return TaskEventRecord(
            event_id=row["event_id"],
            task_id=row["task_id"],
            attempt_id=row["attempt_id"],
            event_type=row["event_type"],
            payload=json.loads(row["payload_json"]),
            created_at=row["created_at"],
        )


class ArtifactRepository(SQLiteRepository):
    """Persist opaque artifact references without reading artifact contents."""

    def register(
        self,
        artifact: ArtifactRecord,
        *,
        latest_checkpoint: bool = False,
    ) -> ArtifactRecord:
        try:
            with self.connection() as connection, connection:
                self.validate_task_attempt_refs(
                    connection, artifact.task_id, artifact.attempt_id
                )
                connection.execute(
                    """
                    INSERT INTO artifacts (
                        artifact_id, task_id, attempt_id, artifact_type, uri,
                        sha256, size_bytes, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artifact.artifact_id,
                        artifact.task_id,
                        artifact.attempt_id,
                        artifact.artifact_type,
                        artifact.uri,
                        artifact.sha256,
                        artifact.size_bytes,
                        _timestamp(artifact.created_at),
                    ),
                )
                if latest_checkpoint:
                    result = connection.execute(
                        """
                        UPDATE tasks SET latest_checkpoint_uri = ?, updated_at = ?
                        WHERE task_id = ?
                        """,
                        (artifact.uri, _timestamp(artifact.created_at), artifact.task_id),
                    )
                    if result.rowcount != 1:
                        raise TaskNotFoundError(f"Task not found: {artifact.task_id}")
                TaskRepository._append_event(
                    connection,
                    artifact.task_id,
                    artifact.attempt_id,
                    "ARTIFACT_REGISTERED",
                    {
                        "artifact_id": artifact.artifact_id,
                        "artifact_type": artifact.artifact_type,
                        "uri": artifact.uri,
                        "sha256": artifact.sha256,
                        "latest_checkpoint": latest_checkpoint,
                    },
                    artifact.created_at,
                )
        except sqlite3.IntegrityError as exc:
            message = str(exc).lower()
            if "artifact_id" in message:
                raise DuplicateRecordError(
                    f"Artifact already exists: {artifact.artifact_id}"
                ) from None
            raise StateConflictError(
                f"Could not register artifact for task {artifact.task_id}"
            ) from None
        return self.get(artifact.artifact_id)

    def get(self, artifact_id: str) -> ArtifactRecord:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
        if row is None:
            raise ArtifactNotFoundError(f"Artifact not found: {artifact_id}")
        return ArtifactRecord.model_validate(dict(row))

    def list_for_task(self, task_id: str) -> list[ArtifactRecord]:
        with self.connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if exists is None:
                raise TaskNotFoundError(f"Task not found: {task_id}")
            rows = connection.execute(
                "SELECT * FROM artifacts WHERE task_id = ? ORDER BY created_at, artifact_id",
                (task_id,),
            ).fetchall()
        return [ArtifactRecord.model_validate(dict(row)) for row in rows]


class ChannelHealthRepository(SQLiteRepository):
    """Persist health for each concrete channel/model surface independently."""

    def upsert(self, record: ChannelHealthRecord) -> ChannelHealthRecord:
        with self.connection() as connection, connection:
            connection.execute(
                """
                INSERT INTO channel_health (
                    channel_id, health, consecutive_failures, last_success_at,
                    last_failure_at, cooldown_until, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    health = excluded.health,
                    consecutive_failures = excluded.consecutive_failures,
                    last_success_at = excluded.last_success_at,
                    last_failure_at = excluded.last_failure_at,
                    cooldown_until = excluded.cooldown_until,
                    metadata_json = excluded.metadata_json
                """,
                (
                    record.channel_id,
                    record.health.value,
                    record.consecutive_failures,
                    _timestamp(record.last_success_at) if record.last_success_at else None,
                    _timestamp(record.last_failure_at) if record.last_failure_at else None,
                    _timestamp(record.cooldown_until) if record.cooldown_until else None,
                    _payload(record.metadata),
                ),
            )
        persisted = self.get(record.channel_id)
        assert persisted is not None
        return persisted

    def get(self, channel_id: str) -> ChannelHealthRecord | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM channel_health WHERE channel_id = ?", (channel_id,)
            ).fetchone()
        if row is None:
            return None
        return ChannelHealthRecord.model_validate(
            {
                "channel_id": row["channel_id"],
                "health": row["health"],
                "consecutive_failures": row["consecutive_failures"],
                "last_success_at": row["last_success_at"],
                "last_failure_at": row["last_failure_at"],
                "cooldown_until": row["cooldown_until"],
                "metadata": json.loads(row["metadata_json"]),
            }
        )


class CostRepository(SQLiteRepository):
    """Persist actual cost observations and their sanitized audit event."""

    def record(
        self,
        *,
        task_id: str,
        channel_id: str,
        billing_mode: str,
        estimated_usd: float,
        created_at: datetime,
        attempt_id: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> CostEventRecord:
        with self.connection() as connection, connection:
            self.validate_task_attempt_refs(connection, task_id, attempt_id)
            cursor = connection.execute(
                """
                INSERT INTO cost_events (
                    task_id, attempt_id, channel_id, billing_mode, input_tokens,
                    output_tokens, estimated_usd, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    attempt_id,
                    channel_id,
                    billing_mode,
                    input_tokens,
                    output_tokens,
                    estimated_usd,
                    _timestamp(created_at),
                ),
            )
            event_id = int(cursor.lastrowid)
            TaskRepository._append_event(
                connection,
                task_id,
                attempt_id,
                "COST_RECORDED",
                {
                    "cost_event_id": event_id,
                    "channel_id": channel_id,
                    "billing_mode": billing_mode,
                    "estimated_usd": estimated_usd,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                },
                created_at,
            )
        return self.get(event_id)

    def get(self, cost_event_id: int) -> CostEventRecord:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM cost_events WHERE cost_event_id = ?", (cost_event_id,)
            ).fetchone()
        if row is None:
            raise TaskNotFoundError(f"Cost event not found: {cost_event_id}")
        return CostEventRecord.model_validate(dict(row))

    def sum_estimated(
        self,
        *,
        task_id: str | None = None,
        since: datetime | None = None,
        before: datetime | None = None,
    ) -> float:
        clauses: list[str] = []
        values: list[str] = []
        if task_id is not None:
            clauses.append("task_id = ?")
            values.append(task_id)
        if since is not None:
            clauses.append("created_at >= ?")
            values.append(_timestamp(since))
        if before is not None:
            clauses.append("created_at < ?")
            values.append(_timestamp(before))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connection() as connection:
            row = connection.execute(
                "SELECT COALESCE(SUM(estimated_usd), 0) FROM cost_events" + where,
                values,
            ).fetchone()
        return float(row[0])

    def list_for_task(self, task_id: str) -> list[CostEventRecord]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM cost_events WHERE task_id = ? ORDER BY cost_event_id",
                (task_id,),
            ).fetchall()
        return [CostEventRecord.model_validate(dict(row)) for row in rows]


class GlobalLearningRepository(SQLiteRepository):
    """Persist only the fixed operational columns defined by the MVP schema."""

    def record(
        self,
        record: GlobalLearningEventRecord,
        *,
        attempt_id: str | None = None,
    ) -> GlobalLearningEventRecord:
        if record.task_id is None:
            raise ValueError("task_id is required for M4 operational metrics")
        with self.connection() as connection, connection:
            self.validate_task_attempt_refs(connection, record.task_id, attempt_id)
            connection.execute(
                """
                INSERT INTO global_learning_events (
                    learning_event_id, task_id, plugin_id, channel_id,
                    capability, success, latency_seconds, estimated_cost_usd,
                    estimated_context_tokens, retries, quality_score, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.learning_event_id,
                    record.task_id,
                    record.plugin_id,
                    record.channel_id,
                    record.capability,
                    int(record.success),
                    record.latency_seconds,
                    record.estimated_cost_usd,
                    record.estimated_context_tokens,
                    record.retries,
                    record.quality_score,
                    _timestamp(record.created_at),
                ),
            )
            TaskRepository._append_event(
                connection,
                record.task_id,
                attempt_id,
                "OPERATIONAL_METRICS_RECORDED",
                {
                    "learning_event_id": record.learning_event_id,
                    "plugin_id": record.plugin_id,
                    "channel_id": record.channel_id,
                    "capability": record.capability,
                    "success": record.success,
                    "latency_seconds": record.latency_seconds,
                    "estimated_cost_usd": record.estimated_cost_usd,
                    "estimated_context_tokens": record.estimated_context_tokens,
                    "retries": record.retries,
                },
                record.created_at,
            )
        return self.get(record.learning_event_id)

    def get(self, learning_event_id: str) -> GlobalLearningEventRecord:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM global_learning_events WHERE learning_event_id = ?",
                (learning_event_id,),
            ).fetchone()
        if row is None:
            raise TaskNotFoundError(
                f"Global learning event not found: {learning_event_id}"
            )
        values = dict(row)
        values["success"] = bool(values["success"])
        return GlobalLearningEventRecord.model_validate(values)

    def list_for_task(self, task_id: str) -> list[GlobalLearningEventRecord]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM global_learning_events
                WHERE task_id = ? ORDER BY created_at, learning_event_id
                """,
                (task_id,),
            ).fetchall()
        results = []
        for row in rows:
            values = dict(row)
            values["success"] = bool(values["success"])
            results.append(GlobalLearningEventRecord.model_validate(values))
        return results


class ApprovalRepository(SQLiteRepository):
    """Create a pending paid-action approval and WAITING state atomically."""

    def request_and_wait(self, approval: ApprovalRecord) -> ApprovalRecord:
        if approval.status != ApprovalStatus.PENDING:
            raise ValueError("new approvals must be PENDING")
        try:
            with self.connection() as connection, connection:
                task = connection.execute(
                    "SELECT status FROM tasks WHERE task_id = ?", (approval.task_id,)
                ).fetchone()
                if task is None:
                    raise TaskNotFoundError(f"Task not found: {approval.task_id}")
                if task["status"] != TaskStatus.RUNNING.value:
                    raise StateConflictError(
                        f"Task {approval.task_id} must be RUNNING to await API approval"
                    )
                connection.execute(
                    """
                    INSERT INTO approvals (
                        approval_id, task_id, action, reason, payload_json, status,
                        requested_at, decided_at, decided_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        approval.approval_id,
                        approval.task_id,
                        approval.action,
                        approval.reason,
                        _payload(approval.payload),
                        approval.status.value,
                        _timestamp(approval.requested_at),
                        None,
                        None,
                    ),
                )
                TaskRepository._append_event(
                    connection,
                    approval.task_id,
                    None,
                    "APPROVAL_REQUESTED",
                    {
                        "approval_id": approval.approval_id,
                        "action": approval.action,
                        "reason": approval.reason,
                        "payload": approval.payload,
                    },
                    approval.requested_at,
                )
                result = connection.execute(
                    """
                    UPDATE tasks SET status = ?, updated_at = ?
                    WHERE task_id = ? AND status = ?
                    """,
                    (
                        TaskStatus.WAITING_APPROVAL.value,
                        _timestamp(approval.requested_at),
                        approval.task_id,
                        TaskStatus.RUNNING.value,
                    ),
                )
                if result.rowcount != 1:
                    raise StateConflictError(
                        f"Task {approval.task_id} changed before approval persistence"
                    )
                TaskRepository._append_event(
                    connection,
                    approval.task_id,
                    None,
                    "TASK_STATUS_CHANGED",
                    {
                        "from_status": TaskStatus.RUNNING.value,
                        "to_status": TaskStatus.WAITING_APPROVAL.value,
                    },
                    approval.requested_at,
                )
        except sqlite3.IntegrityError:
            raise DuplicateRecordError(
                f"Approval already exists: {approval.approval_id}"
            ) from None
        return self.get(approval.approval_id)

    def get(self, approval_id: str) -> ApprovalRecord:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)
            ).fetchone()
        if row is None:
            raise TaskNotFoundError(f"Approval not found: {approval_id}")
        return ApprovalRecord.model_validate(
            {
                "approval_id": row["approval_id"],
                "task_id": row["task_id"],
                "action": row["action"],
                "reason": row["reason"],
                "payload": json.loads(row["payload_json"]),
                "status": row["status"],
                "requested_at": row["requested_at"],
                "decided_at": row["decided_at"],
                "decided_by": row["decided_by"],
            }
        )

    def decide(self, approval_id: str, status: ApprovalStatus, decided_by: str) -> ApprovalRecord:
        """Decide one pending approval and resume or fail its waiting task."""
        if status not in {ApprovalStatus.APPROVED, ApprovalStatus.DENIED}:
            raise ValueError("approval decision must be APPROVED or DENIED")
        if not decided_by:
            raise ValueError("decided_by must not be empty")
        now = datetime.now().astimezone()
        with self.connection() as connection, connection:
            row = connection.execute(
                "SELECT task_id, status FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if row is None:
                raise TaskNotFoundError(f"Approval not found: {approval_id}")
            if row["status"] != ApprovalStatus.PENDING.value:
                raise StateConflictError(f"Approval {approval_id} is already decided")
            connection.execute(
                "UPDATE approvals SET status = ?, decided_at = ?, decided_by = ? WHERE approval_id = ? AND status = ?",
                (status.value, _timestamp(now), decided_by, approval_id, ApprovalStatus.PENDING.value),
            )
            target = TaskStatus.RUNNING if status == ApprovalStatus.APPROVED else TaskStatus.FAILED
            task_row = connection.execute("SELECT status FROM tasks WHERE task_id = ?", (row["task_id"],)).fetchone()
            if task_row is None:
                raise TaskNotFoundError(f"Task not found: {row['task_id']}")
            if task_row["status"] == TaskStatus.WAITING_APPROVAL.value:
                connection.execute("UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ? AND status = ?",
                                   (target.value, _timestamp(now), row["task_id"], TaskStatus.WAITING_APPROVAL.value))
                TaskRepository._append_event(connection, row["task_id"], None, "TASK_STATUS_CHANGED",
                                             {"from_status": TaskStatus.WAITING_APPROVAL.value, "to_status": target.value}, now)
            TaskRepository._append_event(connection, row["task_id"], None, "APPROVAL_DECIDED",
                                         {"approval_id": approval_id, "status": status.value, "decided_by": decided_by}, now)
        return self.get(approval_id)

    def list_for_task(self, task_id: str) -> list[ApprovalRecord]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM approvals WHERE task_id = ? ORDER BY requested_at, approval_id",
                (task_id,),
            ).fetchall()
        return [
            ApprovalRecord.model_validate(
                {
                    "approval_id": row["approval_id"],
                    "task_id": row["task_id"],
                    "action": row["action"],
                    "reason": row["reason"],
                    "payload": json.loads(row["payload_json"]),
                    "status": row["status"],
                    "requested_at": row["requested_at"],
                    "decided_at": row["decided_at"],
                    "decided_by": row["decided_by"],
                }
            )
            for row in rows
        ]
