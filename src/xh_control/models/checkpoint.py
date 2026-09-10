"""Versioned, global checkpoint contract.

The plugin state reference is intentionally opaque.  Global Control validates
only its own identity, execution fence, and the registered artifact refs.
"""

from datetime import datetime

from pydantic import Field

from .base import ContractModel


class GlobalCheckpoint(ContractModel):
    schema_version: str = "1.0"
    checkpoint_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    task_id: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    generation: int = Field(ge=1)
    plugin: str = Field(min_length=1)
    plugin_state_ref: str = Field(min_length=1)
    global_status: str = Field(min_length=1)
    worker_id: str = Field(min_length=1)
    channel_id: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    next_global_action: str = Field(min_length=1)
    created_at: datetime
    payload_sha256: str = Field(min_length=64, max_length=64)
