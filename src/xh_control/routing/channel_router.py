"""Deterministic capability-first, subscription-first channel routing."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import math

from xh_control.config import Configuration
from xh_control.exceptions import NoEligibleChannelError
from xh_control.models import (
    ChannelClass,
    ChannelHealth,
    CostMode,
    ExecutionChannel,
    TaskEnvelope,
)
from xh_control.state import ChannelHealthRepository

from .master_selector import MasterSelector


def _now() -> datetime:
    return datetime.now(UTC)


HEALTH_SCORE = {
    ChannelHealth.AVAILABLE: 1.0,
    ChannelHealth.DEGRADED: 0.6,
    ChannelHealth.LIMIT_WARNING: 0.4,
    ChannelHealth.UNKNOWN: 0.0,
}

MONETARY_COST_SCORE = {
    ChannelClass.SUBSCRIPTION: 0.0,
    ChannelClass.FREE_LOCAL: 0.0,
    ChannelClass.CHEAP_API: 1.0,
    ChannelClass.PREMIUM_API: 2.0,
}


@dataclass(frozen=True, slots=True)
class RankedChannel:
    channel: ExecutionChannel
    effective_health: ChannelHealth
    score: float


class ChannelRouter:
    """Resolve MASTER by channel class first, then deterministic scoring."""

    def __init__(
        self,
        configuration: Configuration,
        *,
        health_repository: ChannelHealthRepository | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.configuration = configuration
        self.health_repository = health_repository
        self.clock = clock
        self.master_selector = MasterSelector(configuration.subscriptions)

    def resolve_master_channel(
        self,
        *,
        task: TaskEnvelope,
        worker_id: str,
        current_channel_id: str | None = None,
    ) -> ExecutionChannel:
        ranked = self.rank_candidates(
            task=task,
            worker_id=worker_id,
            current_channel_id=current_channel_id,
        )
        return self.master_selector.select(
            preference=task.execution.master_preference,
            ranked_channels=[item.channel for item in ranked],
            all_channels=self.configuration.channels,
            allow_cross_provider=self.configuration.routing.fallback.allow_cross_provider,
        )

    def rank_candidates(
        self,
        *,
        task: TaskEnvelope,
        worker_id: str,
        current_channel_id: str | None = None,
    ) -> tuple[RankedChannel, ...]:
        required = task.execution.master_capability
        mode = task.execution.cost_mode
        mode_policy = self.configuration.routing.modes[mode]
        disabled_subscriptions = {
            item.preferred_channel
            for item in self.configuration.subscriptions.values()
            if not item.enabled
        }
        candidates: list[RankedChannel] = []
        now = self.clock()
        for channel in self.configuration.channels.values():
            effective_health = self._effective_health(channel, now)
            if (
                not channel.enabled
                or required not in channel.capabilities
                or effective_health in {
                    ChannelHealth.UNAVAILABLE,
                    ChannelHealth.RATE_LIMITED,
                }
                or channel.channel_id in disabled_subscriptions
                or (
                    channel.channel_class == ChannelClass.PREMIUM_API
                    and not mode_policy.premium_api_allowed
                )
            ):
                continue
            candidates.append(
                RankedChannel(
                    channel=channel,
                    effective_health=effective_health,
                    score=self._score(
                        channel,
                        effective_health,
                        worker_id=worker_id,
                        current_channel_id=current_channel_id,
                        mode=mode,
                    ),
                )
            )
        candidates.sort(key=self._sort_key)
        if not candidates:
            raise NoEligibleChannelError(
                f"No eligible channel provides capability {required} in mode {mode.value}"
            )
        return tuple(candidates)

    def _effective_health(
        self,
        channel: ExecutionChannel,
        now: datetime,
    ) -> ChannelHealth:
        if self.health_repository is None:
            return channel.health
        state = self.health_repository.get(channel.channel_id)
        return state.effective_health(now) if state is not None else channel.health

    def _score(
        self,
        channel: ExecutionChannel,
        health: ChannelHealth,
        *,
        worker_id: str,
        current_channel_id: str | None,
        mode: CostMode,
    ) -> float:
        weights = self.configuration.routing.weights
        metadata = channel.metadata
        worker_ids = metadata.get("worker_ids")
        worker_affinity = (
            0.5
            if worker_ids is None
            else float(worker_id in worker_ids)
        )
        quality_default = 0.8 if mode == CostMode.MAX_QUALITY else 0.7
        quality = self._metric(metadata, "quality_score", quality_default)
        health_reliability = HEALTH_SCORE.get(health, 0.0)
        reliability = min(
            self._metric(metadata, "reliability_score", health_reliability),
            health_reliability,
        )
        token_cost = self._metric(metadata, "token_cost_score", 0.0)
        latency = self._metric(metadata, "latency_score", 0.0)
        handoff = float(
            current_channel_id is not None and current_channel_id != channel.channel_id
        )
        return (
            weights.capability_fit
            + weights.subscription_bonus
            * float(channel.channel_class == ChannelClass.SUBSCRIPTION)
            + weights.quality * quality
            + weights.reliability * reliability
            + weights.worker_affinity * worker_affinity
            + weights.monetary_cost * MONETARY_COST_SCORE[channel.channel_class]
            + weights.token_cost * token_cost
            + weights.latency * latency
            + weights.handoff_penalty * handoff
        )

    @staticmethod
    def _metric(metadata: dict, name: str, default: float) -> float:
        value = float(metadata.get(name, default))
        if not math.isfinite(value):
            raise ValueError(f"channel metadata metric {name} must be finite")
        return value

    def _sort_key(self, item: RankedChannel) -> tuple[float, float, int, str]:
        # Channel class is deliberately the first and independent sort dimension.
        # This prevents a paid API score from overtaking a capable subscription.
        class_priority = self.configuration.routing.class_priority[
            item.channel.channel_class
        ]
        return (
            -float(class_priority),
            -item.score,
            -item.channel.priority,
            item.channel.channel_id,
        )
