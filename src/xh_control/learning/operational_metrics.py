"""Persist measured channel cost, latency, and token observations."""

from collections.abc import Callable
from datetime import UTC, datetime
import math
from uuid import uuid4

from xh_control.channels import ChannelResponse
from xh_control.models import ChannelClass, ExecutionChannel, GlobalLearningEventRecord
from xh_control.state import CostRepository, GlobalLearningRepository


def _now() -> datetime:
    return datetime.now(UTC)


def _new_learning_event_id() -> str:
    return f"LE-{uuid4().hex[:16].upper()}"


class OperationalMetricsService:
    """Store only observed or policy-known operational values."""

    def __init__(
        self,
        cost_repository: CostRepository,
        learning_repository: GlobalLearningRepository,
        *,
        clock: Callable[[], datetime] = _now,
        learning_event_id_factory: Callable[[], str] = _new_learning_event_id,
    ) -> None:
        self.cost_repository = cost_repository
        self.learning_repository = learning_repository
        self.clock = clock
        self.learning_event_id_factory = learning_event_id_factory

    def record_channel_response(
        self,
        *,
        task_id: str,
        attempt_id: str,
        plugin_id: str,
        capability: str,
        channel: ExecutionChannel,
        response: ChannelResponse,
        retries: int = 0,
    ) -> GlobalLearningEventRecord:
        input_tokens = self._reported_int(response.usage, "input_tokens")
        output_tokens = self._reported_int(response.usage, "output_tokens")
        # Provider cache counters do not have identical semantics and may be a
        # subset of input_tokens. Never add them and risk double counting.
        context_tokens = input_tokens
        estimated_cost = self._reported_money(response.usage, "estimated_usd")
        if channel.channel_class == ChannelClass.SUBSCRIPTION:
            estimated_cost = 0.0
        now = self.clock()
        if estimated_cost is not None:
            self.cost_repository.record(
                task_id=task_id,
                attempt_id=attempt_id,
                channel_id=channel.channel_id,
                billing_mode=channel.billing_mode,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_usd=estimated_cost,
                created_at=now,
            )
        return self.learning_repository.record(
            GlobalLearningEventRecord(
                learning_event_id=self.learning_event_id_factory(),
                task_id=task_id,
                plugin_id=plugin_id,
                channel_id=channel.channel_id,
                capability=capability,
                success=response.success,
                latency_seconds=response.latency_seconds,
                estimated_cost_usd=estimated_cost,
                estimated_context_tokens=context_tokens,
                retries=retries,
                created_at=now,
            ),
            attempt_id=attempt_id,
        )

    @staticmethod
    def _reported_int(usage: dict, key: str) -> int | None:
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return None

    @staticmethod
    def _reported_money(usage: dict, key: str) -> float | None:
        value = usage.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            number = float(value)
            if math.isfinite(number) and number >= 0:
                return number
        return None
