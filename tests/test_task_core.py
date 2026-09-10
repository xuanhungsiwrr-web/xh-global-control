from datetime import UTC, datetime
import sqlite3

import pytest
from pydantic import ValidationError

from xh_control.config import load_config
from xh_control.core import ArtifactService, EventService, TaskService
from xh_control.core.state_machine import ALLOWED_TASK_TRANSITIONS, validate_task_transition
from xh_control.exceptions import (
    InvalidGenerationError,
    InvalidTaskTransitionError,
    StateConflictError,
    TaskNotFoundError,
)
from xh_control.models import TaskEnvelope, TaskStatus
from xh_control.state import (
    ArtifactRepository,
    EventRepository,
    TaskRepository,
    initialize_database,
)

NOW = datetime(2026, 9, 8, 3, 4, 5, tzinfo=UTC)


def envelope(task_id="T-CORE-1"):
    return TaskEnvelope(
        task_id=task_id,
        created_at=NOW,
        task_type="generic",
        plugin="generic-plugin",
        project={"project_id": "P-1", "workspace_uri": "file:///project"},
        execution={},
        permissions={},
        budget={"api_soft_usd": 1, "api_hard_usd": 3},
        user_request="Opaque request",
    )


@pytest.fixture
def task_core(config_root):
    path = initialize_database(load_config(config_root))
    task_ids = iter(["A-ONE", "A-TWO", "A-THREE"])
    artifact_ids = iter(["AR-ONE", "AR-TWO"])
    tasks = TaskService(
        TaskRepository(path), clock=lambda: NOW, attempt_id_factory=lambda: next(task_ids)
    )
    events = EventService(EventRepository(path), clock=lambda: NOW)
    artifacts = ArtifactService(
        ArtifactRepository(path),
        clock=lambda: NOW,
        artifact_id_factory=lambda: next(artifact_ids),
    )
    return path, tasks, events, artifacts


def test_task_creation_and_persistence_after_reopen(task_core):
    path, tasks, events, _ = task_core
    created = tasks.create_task(envelope())
    assert created.status == TaskStatus.CREATED
    assert events.list_for_task(created.task.task_id)[0].event_type == "TASK_CREATED"

    reopened = TaskService(TaskRepository(path)).get_task(created.task.task_id)
    assert reopened == created
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_every_declared_transition_is_accepted_by_central_policy():
    for current, targets in ALLOWED_TASK_TRANSITIONS.items():
        for target in targets:
            validate_task_transition(current, target)


@pytest.mark.parametrize(
    "current,target",
    [
        (TaskStatus.CREATED, TaskStatus.RUNNING),
        (TaskStatus.RUNNING, TaskStatus.CREATED),
        (TaskStatus.COMPLETED, TaskStatus.RUNNING),
        (TaskStatus.CANCELLED, TaskStatus.CANCELLED),
    ],
)
def test_forbidden_transitions_are_rejected(current, target):
    with pytest.raises(
        InvalidTaskTransitionError,
        match=rf"{current.value} -> {target.value}",
    ):
        validate_task_transition(current, target)


def test_persisted_transitions_create_ordered_audit_events(task_core):
    _, tasks, events, _ = task_core
    tasks.create_task(envelope())
    assert tasks.transition_task("T-CORE-1", TaskStatus.QUEUED).status == TaskStatus.QUEUED
    assert tasks.transition_task("T-CORE-1", TaskStatus.PAUSED).status == TaskStatus.PAUSED
    assert tasks.transition_task("T-CORE-1", TaskStatus.QUEUED).status == TaskStatus.QUEUED
    assert [event.event_type for event in events.list_for_task("T-CORE-1")] == [
        "TASK_CREATED",
        "TASK_STATUS_CHANGED",
        "TASK_STATUS_CHANGED",
        "TASK_STATUS_CHANGED",
    ]
    assert events.list_for_task("T-CORE-1")[-1].payload == {
        "from_status": "PAUSED",
        "to_status": "QUEUED",
    }


def test_attempt_numbering_generation_and_fencing(task_core):
    _, tasks, events, _ = task_core
    tasks.create_task(envelope())
    tasks.transition_task("T-CORE-1", TaskStatus.QUEUED)
    first = tasks.create_attempt("T-CORE-1", "pc-main", "codex-subscription")
    assert (first.attempt_no, first.generation, first.attempt_id) == (1, 1, "A-ONE")
    assert tasks.validate_fence("T-CORE-1", "A-ONE", 1) == first

    second = tasks.create_attempt("T-CORE-1", "pc-main", "claude-code-subscription")
    assert (second.attempt_no, second.generation, second.attempt_id) == (2, 2, "A-TWO")
    assert tasks.get_task("T-CORE-1").current_attempt_id == "A-TWO"
    with pytest.raises(InvalidGenerationError, match="Stale"):
        tasks.validate_fence("T-CORE-1", "A-ONE", 1)
    with pytest.raises(InvalidGenerationError, match="requires generation 3"):
        tasks.create_attempt("T-CORE-1", "pc-main", generation=4)
    assert [(item.attempt_no, item.generation) for item in tasks.list_attempts("T-CORE-1")] == [
        (1, 1),
        (2, 2),
    ]
    assert [event.event_type for event in events.list_for_task("T-CORE-1")].count(
        "ATTEMPT_CREATED"
    ) == 2


def test_fenced_state_change_accepts_only_current_generation(task_core):
    _, tasks, _, _ = task_core
    tasks.create_task(envelope())
    tasks.transition_task("T-CORE-1", TaskStatus.QUEUED)
    attempt = tasks.create_attempt("T-CORE-1", "pc-main")
    assigned = tasks.transition_task(
        "T-CORE-1",
        TaskStatus.ASSIGNED,
        attempt_id=attempt.attempt_id,
        generation=attempt.generation,
    )
    assert assigned.status == TaskStatus.ASSIGNED
    with pytest.raises(InvalidGenerationError):
        tasks.transition_task(
            "T-CORE-1",
            TaskStatus.RUNNING,
            attempt_id=attempt.attempt_id,
            generation=99,
        )
    assert tasks.get_task("T-CORE-1").status == TaskStatus.ASSIGNED


def test_attempt_lifecycle_timestamps_failure_and_audit(task_core):
    path, tasks, events, _ = task_core
    tasks.create_task(envelope())
    attempt = tasks.create_attempt("T-CORE-1", "pc-main", "codex-subscription")
    running = tasks.transition_attempt(
        "T-CORE-1", attempt.attempt_id, attempt.generation, TaskStatus.RUNNING
    )
    assert running.started_at == NOW
    assert running.ended_at is None
    failed = tasks.transition_attempt(
        "T-CORE-1",
        attempt.attempt_id,
        attempt.generation,
        TaskStatus.FAILED,
        failure_type="CHANNEL_FAILURE",
        failure_message="deterministic test failure",
    )
    assert failed.failure_type == "CHANNEL_FAILURE"
    assert failed.failure_message == "deterministic test failure"
    assert failed.started_at == NOW
    assert failed.ended_at == NOW
    assert [event.event_type for event in events.list_for_task("T-CORE-1")][-2:] == [
        "ATTEMPT_STATUS_CHANGED",
        "ATTEMPT_STATUS_CHANGED",
    ]

    reopened = TaskService(TaskRepository(path)).get_attempt(attempt.attempt_id)
    assert reopened == failed
    with pytest.raises(InvalidTaskTransitionError):
        tasks.transition_attempt(
            "T-CORE-1", attempt.attempt_id, attempt.generation, TaskStatus.RUNNING
        )


def test_stale_attempt_cannot_write_attempt_state(task_core):
    _, tasks, _, _ = task_core
    tasks.create_task(envelope())
    first = tasks.create_attempt("T-CORE-1", "pc-main")
    tasks.create_attempt("T-CORE-1", "pc-main")
    with pytest.raises(InvalidGenerationError, match="Stale"):
        tasks.transition_attempt(
            "T-CORE-1", first.attempt_id, first.generation, TaskStatus.RUNNING
        )


def test_artifact_registry_and_checkpoint_reference_are_transactional(task_core):
    path, tasks, events, artifacts = task_core
    tasks.create_task(envelope())
    artifact = artifacts.register(
        "T-CORE-1",
        "checkpoint",
        "drive://project/.ai/checkpoints/CP-0001.json",
        sha256="abc123",
        size_bytes=42,
        latest_checkpoint=True,
    )
    assert artifacts.get(artifact.artifact_id) == artifact
    assert artifacts.list_for_task("T-CORE-1") == [artifact]
    assert tasks.get_task("T-CORE-1").latest_checkpoint_uri == artifact.uri
    assert events.list_for_task("T-CORE-1")[-1].payload["sha256"] == "abc123"

    reopened = ArtifactService(ArtifactRepository(path)).get(artifact.artifact_id)
    assert reopened == artifact


def test_cross_task_attempt_reference_is_rejected_without_partial_write(task_core):
    _, tasks, events, artifacts = task_core
    tasks.create_task(envelope("T-ONE"))
    tasks.create_task(envelope("T-TWO"))
    attempt = tasks.create_attempt("T-ONE", "pc-main")
    with pytest.raises(StateConflictError):
        artifacts.register("T-TWO", "output", "drive://output", attempt_id=attempt.attempt_id)
    with pytest.raises(StateConflictError):
        events.append("T-TWO", "BAD_REF", {}, attempt_id=attempt.attempt_id)
    assert artifacts.list_for_task("T-TWO") == []
    assert [event.event_type for event in events.list_for_task("T-TWO")] == ["TASK_CREATED"]


def test_missing_and_malformed_required_data_fail_predictably(task_core):
    _, tasks, events, artifacts = task_core
    with pytest.raises(ValidationError):
        envelope().model_copy(update={"user_request": ""}).__class__.model_validate(
            envelope().model_dump() | {"user_request": ""}
        )
    with pytest.raises(TaskNotFoundError, match="MISSING"):
        tasks.get_task("MISSING")
    with pytest.raises(TaskNotFoundError, match="MISSING"):
        events.list_for_task("MISSING")
    with pytest.raises(TaskNotFoundError, match="MISSING"):
        artifacts.list_for_task("MISSING")
