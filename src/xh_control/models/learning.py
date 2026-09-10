"""Operational-only learning records persisted by Global Control."""

from datetime import datetime

from pydantic import Field

from .base import ContractModel


class GlobalLearningEventRecord(ContractModel):
    learning_event_id: str = Field(min_length=1)
    task_id: str | None = None
    plugin_id: str | None = None
    channel_id: str | None = None
    capability: str | None = None
    success: bool
    latency_seconds: float | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    estimated_context_tokens: int | None = Field(default=None, ge=0)
    retries: int | None = Field(default=None, ge=0)
    quality_score: float | None = Field(default=None, ge=0, le=1)
    created_at: datetime
