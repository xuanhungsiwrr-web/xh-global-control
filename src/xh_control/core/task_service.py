"""M1 task lifecycle and attempt tracking service."""

from collections.abc import Callable
from datetime import UTC, datetime

from xh_control.exceptions import InvalidGenerationError, InvalidTaskTransitionError
from xh_control.models import (
    ExecutionAttemptRecord,
    FailureType,
    TaskEnvelope,
    TaskRecord,
    TaskStatus,
)
from xh_control.state.repositories import TaskRepository

from .identifiers import new_attempt_id
from .state_machine import TERMINAL_TASK_STATUSES, validate_task_transition


def _now() -> datetime:
    return datetime.now(UTC)


class TaskService:
    """Own lifecycle policy while keeping SQL behind a repository boundary."""

    def __init__(
        self,
        repository: TaskRepository,
        *,
        clock: Callable[[], datetime] = _now,
        attempt_id_factory: Callable[[], str] = new_attempt_id,
    ) -> None:
        self.repository = repository
        self.clock = clock
        self.attempt_id_factory = attempt_id_factory

    def create_task(self, task: TaskEnvelope) -> TaskRecord:
        return self.repository.create(task, self.clock())

    def get_task(self, task_id: str) -> TaskRecord:
        return self.repository.get(task_id)

    def list_tasks(self, limit: int = 100) -> list[TaskRecord]:
        return self.repository.list(limit)

    def transition_task(
        self,
        task_id: str,
        target: TaskStatus,
        *,
        attempt_id: str | None = None,
        generation: int | None = None,
    ) -> TaskRecord:
        current = self.repository.get(task_id)
        validate_task_transition(current.status, target)
        if attempt_id is not None or generation is not None:
            self.validate_fence(task_id, attempt_id, generation)
        return self.repository.transition(
            task_id,
            current.status,
            target,
            self.clock(),
            attempt_id=attempt_id,
            generation=generation,
        )

    def create_attempt(
        self,
        task_id: str,
        worker_id: str,
        channel_id: str | None = None,
        *,
        generation: int | None = None,
        attempt_id: str | None = None,
    ) -> ExecutionAttemptRecord:
        if not worker_id:
            raise ValueError("worker_id must not be empty")
        task = self.repository.get(task_id)
        if task.status in TERMINAL_TASK_STATUSES:
            raise InvalidTaskTransitionError(
                f"Cannot create an attempt for terminal task {task_id} ({task.status.value})"
            )
        return self.repository.create_attempt(
            task_id,
            attempt_id or self.attempt_id_factory(),
            worker_id,
            channel_id,
            self.clock(),
            generation,
        )

    def get_attempt(self, attempt_id: str) -> ExecutionAttemptRecord:
        return self.repository.get_attempt(attempt_id)

    def list_attempts(self, task_id: str) -> list[ExecutionAttemptRecord]:
        return self.repository.list_attempts(task_id)

    def transition_attempt(
        self,
        task_id: str,
        attempt_id: str,
        generation: int,
        target: TaskStatus,
        *,
        failure_type: FailureType | None = None,
        failure_message: str | None = None,
    ) -> ExecutionAttemptRecord:
        current = self.validate_fence(task_id, attempt_id, generation)
        validate_task_transition(current.status, target)
        if failure_type is not None and not isinstance(failure_type, FailureType):
            failure_type = FailureType(failure_type)
        if target != TaskStatus.FAILED and (failure_type is not None or failure_message is not None):
            raise ValueError("failure details are valid only for a FAILED attempt")
        return self.repository.transition_attempt(
            task_id,
            attempt_id,
            generation,
            current.status,
            target,
            self.clock(),
            failure_type=failure_type,
            failure_message=failure_message,
        )

    def validate_fence(
        self,
        task_id: str,
        attempt_id: str | None,
        generation: int | None,
    ) -> ExecutionAttemptRecord:
        """Reject a stale or incomplete attempt/generation fencing token."""
        if not attempt_id or generation is None:
            raise InvalidGenerationError("attempt_id and generation must be supplied together")
        task = self.repository.get(task_id)
        attempt = self.repository.get_attempt(attempt_id)
        if (
            attempt.task_id != task_id
            or task.current_attempt_id != attempt_id
            or attempt.generation != generation
        ):
            raise InvalidGenerationError(
                f"Stale attempt generation for task {task_id}: {attempt_id}/{generation}"
            )
        return attempt
