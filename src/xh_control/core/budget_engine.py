"""Deterministic API budget authorization across task, daily, and monthly scopes."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import math

from xh_control.config import BudgetsConfig
from xh_control.core.identifiers import new_approval_id
from xh_control.core.state_machine import validate_task_transition
from xh_control.exceptions import BudgetStateError, InvalidTaskTransitionError
from xh_control.models import (
    ApprovalRecord,
    ApprovalStatus,
    BudgetAuthorization,
    BudgetDecision,
    ChannelClass,
    ExecutionChannel,
    TaskStatus,
)
from xh_control.state import ApprovalRepository, CostRepository

from .event_service import EventService
from .task_service import TaskService


def _now() -> datetime:
    return datetime.now(UTC)


PAID_API_CLASSES = frozenset(
    {ChannelClass.CHEAP_API, ChannelClass.PREMIUM_API}
)


class BudgetEngine:
    """Authorize projected API spend without blocking zero-cost alternatives."""

    def __init__(
        self,
        *,
        budgets: BudgetsConfig,
        task_service: TaskService,
        event_service: EventService,
        cost_repository: CostRepository,
        approval_repository: ApprovalRepository,
        clock: Callable[[], datetime] = _now,
        approval_id_factory: Callable[[], str] = new_approval_id,
    ) -> None:
        self.budgets = budgets
        self.task_service = task_service
        self.event_service = event_service
        self.cost_repository = cost_repository
        self.approval_repository = approval_repository
        self.clock = clock
        self.approval_id_factory = approval_id_factory

    def authorize(
        self,
        *,
        task_id: str,
        channel: ExecutionChannel,
        expected_cost_usd: float,
    ) -> BudgetAuthorization:
        self._validate_money(expected_cost_usd)
        record = self.task_service.get_task(task_id)
        now = self._aware_now()
        task_spend = self.cost_repository.sum_estimated(task_id=task_id)
        daily_spend = self.cost_repository.sum_estimated(
            since=self._day_start(now), before=self._next_day(now)
        )
        monthly_spend = self.cost_repository.sum_estimated(
            since=self._month_start(now), before=self._next_month(now)
        )

        if channel.channel_class not in PAID_API_CLASSES:
            if expected_cost_usd != 0:
                raise ValueError("subscription/local authorization must have zero API cost")
            result = BudgetAuthorization(
                decision=BudgetDecision.ALLOW,
                expected_cost_usd=0,
                projected_task_usd=task_spend,
                projected_daily_usd=daily_spend,
                projected_monthly_usd=monthly_spend,
            )
            self.event_service.append(
                task_id,
                "NON_PAID_CHANNEL_AUTHORIZED",
                {
                    "channel_id": channel.channel_id,
                    "channel_class": channel.channel_class.value,
                    "billing_mode": channel.billing_mode,
                },
            )
            return result

        projected_task = task_spend + expected_cost_usd
        projected_daily = daily_spend + expected_cost_usd
        projected_monthly = monthly_spend + expected_cost_usd
        hard_scopes = tuple(
            name
            for name, projected, limit in (
                ("task", projected_task, record.task.budget.api_hard_usd),
                ("daily", projected_daily, self.budgets.daily.api_hard_usd),
                (
                    "global_monthly",
                    projected_monthly,
                    self.budgets.global_budget.monthly_api_hard_usd,
                ),
            )
            if projected > limit
        )
        warning_scopes = tuple(
            name
            for name, projected, limit in (
                ("task", projected_task, record.task.budget.api_soft_usd),
                ("daily", projected_daily, self.budgets.daily.api_soft_usd),
            )
            if projected > limit
        )

        common = {
            "expected_cost_usd": expected_cost_usd,
            "projected_task_usd": projected_task,
            "projected_daily_usd": projected_daily,
            "projected_monthly_usd": projected_monthly,
            "warning_scopes": warning_scopes,
            "hard_limit_scopes": hard_scopes,
        }
        if hard_scopes:
            try:
                validate_task_transition(record.status, TaskStatus.WAITING_APPROVAL)
            except InvalidTaskTransitionError:
                raise BudgetStateError(
                    f"Task {task_id} must be RUNNING before a paid action can await approval"
                ) from None
            approval_id = self.approval_id_factory()
            approval = ApprovalRecord(
                approval_id=approval_id,
                task_id=task_id,
                action="EXCEED_API_HARD_LIMIT",
                reason="Projected API spend exceeds one or more configured hard limits",
                payload={
                    "channel_id": channel.channel_id,
                    "billing_mode": channel.billing_mode,
                    **common,
                },
                status=ApprovalStatus.PENDING,
                requested_at=now,
            )
            self.approval_repository.request_and_wait(approval)
            return BudgetAuthorization(
                decision=BudgetDecision.BLOCK_PENDING_APPROVAL,
                approval_id=approval_id,
                **common,
            )

        decision = (
            BudgetDecision.ALLOW_WITH_WARNING
            if warning_scopes
            else BudgetDecision.ALLOW
        )
        event_type = (
            "API_BUDGET_WARNING"
            if decision == BudgetDecision.ALLOW_WITH_WARNING
            else "API_BUDGET_AUTHORIZED"
        )
        self.event_service.append(
            task_id,
            event_type,
            {
                "channel_id": channel.channel_id,
                "billing_mode": channel.billing_mode,
                **common,
            },
        )
        return BudgetAuthorization(decision=decision, **common)

    def record_cost(
        self,
        *,
        task_id: str,
        channel: ExecutionChannel,
        estimated_usd: float,
        attempt_id: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ):
        self._validate_money(estimated_usd)
        return self.cost_repository.record(
            task_id=task_id,
            attempt_id=attempt_id,
            channel_id=channel.channel_id,
            billing_mode=channel.billing_mode,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_usd=estimated_usd,
            created_at=self._aware_now(),
        )

    def _aware_now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("budget clock must return a timezone-aware datetime")
        return value

    @staticmethod
    def _validate_money(value: float) -> None:
        if isinstance(value, bool) or not math.isfinite(value) or value < 0:
            raise ValueError("cost must be a finite non-negative number")

    @staticmethod
    def _day_start(now: datetime) -> datetime:
        return now.replace(hour=0, minute=0, second=0, microsecond=0)

    @classmethod
    def _next_day(cls, now: datetime) -> datetime:
        return cls._day_start(now) + timedelta(days=1)

    @staticmethod
    def _month_start(now: datetime) -> datetime:
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    @classmethod
    def _next_month(cls, now: datetime) -> datetime:
        start = cls._month_start(now)
        if start.month == 12:
            return start.replace(year=start.year + 1, month=1)
        return start.replace(month=start.month + 1)
