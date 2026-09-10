"""Persistent artifact registry records."""

from datetime import datetime

from pydantic import Field

from .base import ContractModel


class ArtifactRecord(ContractModel):
    artifact_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    attempt_id: str | None = None
    artifact_type: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    sha256: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    created_at: datetime
