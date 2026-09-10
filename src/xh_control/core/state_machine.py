"""Central, deterministic task state-transition policy."""

from xh_control.exceptions import InvalidTaskTransitionError
from xh_control.models import TaskStatus


TERMINAL_TASK_STATUSES = frozenset(
    {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
)

ALLOWED_TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset({TaskStatus.QUEUED, TaskStatus.FAILED, TaskStatus.CANCELLED}),
    TaskStatus.QUEUED: frozenset(
        {TaskStatus.ASSIGNED, TaskStatus.PAUSED, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.ASSIGNED: frozenset(
        {
            TaskStatus.RUNNING,
            TaskStatus.PAUSED,
            TaskStatus.RETRYING,
            TaskStatus.FAILOVER_PENDING,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.PAUSED,
            TaskStatus.RETRYING,
            TaskStatus.FAILOVER_PENDING,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.WAITING_APPROVAL: frozenset(
        {TaskStatus.RUNNING, TaskStatus.PAUSED, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.PAUSED: frozenset(
        {TaskStatus.QUEUED, TaskStatus.ASSIGNED, TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.RETRYING: frozenset(
        {TaskStatus.ASSIGNED, TaskStatus.RUNNING, TaskStatus.FAILOVER_PENDING, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.FAILOVER_PENDING: frozenset(
        {TaskStatus.ASSIGNED, TaskStatus.RETRYING, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


def validate_task_transition(current: TaskStatus, target: TaskStatus) -> None:
    """Reject no-op and forbidden state changes with a stable message."""
    if target not in ALLOWED_TASK_TRANSITIONS[current]:
        raise InvalidTaskTransitionError(
            f"Task transition {current.value} -> {target.value} is not permitted"
        )
