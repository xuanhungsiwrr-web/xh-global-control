"""Append-only operational audit event service."""

from collections.abc import Callable
from datetime import UTC, datetime

from xh_control.models import TaskEventRecord
from xh_control.state.repositories import EventRepository


def _now() -> datetime:
    return datetime.now(UTC)


class EventService:
    def __init__(
        self,
        repository: EventRepository,
        *,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.repository = repository
        self.clock = clock

    def append(
        self,
        task_id: str,
        event_type: str,
        payload: dict,
        *,
        attempt_id: str | None = None,
    ) -> TaskEventRecord:
        if not event_type:
            raise ValueError("event_type must not be empty")
        return self.repository.append(
            task_id, event_type, payload, self.clock(), attempt_id
        )

    def list_for_task(self, task_id: str) -> list[TaskEventRecord]:
        return self.repository.list_for_task(task_id)
