"""Persisted health state for one concrete execution channel."""

from datetime import datetime

from pydantic import Field

from .base import ContractModel
from .enums import ChannelHealth


class ChannelHealthRecord(ContractModel):
    channel_id: str = Field(min_length=1)
    health: ChannelHealth
    consecutive_failures: int = Field(default=0, ge=0)
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    cooldown_until: datetime | None = None
    metadata: dict = Field(default_factory=dict)

    def effective_health(self, now: datetime) -> ChannelHealth:
        if self.cooldown_until is not None and now < self.cooldown_until:
            return ChannelHealth.RATE_LIMITED
        return self.health
