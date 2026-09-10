"""Opaque identifiers for persistent task-core records."""

from datetime import datetime
from uuid import uuid4


def new_task_id(now: datetime) -> str:
    return f"T-{now:%Y%m%d}-{uuid4().hex[:12].upper()}"


def new_attempt_id() -> str:
    return f"A-{uuid4().hex[:16].upper()}"


def new_artifact_id() -> str:
    return f"AR-{uuid4().hex[:16].upper()}"


def new_approval_id() -> str:
    return f"AP-{uuid4().hex[:16].upper()}"
