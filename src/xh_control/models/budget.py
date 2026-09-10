"""Budget decisions and persisted cost/approval records."""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from .base import ContractModel


class BudgetDecision(StrEnum):
    ALLOW = "ALLOW"
    ALLOW_WITH_WARNING = "ALLOW_WITH_WARNING"
    BLOCK_PENDING_APPROVAL = "BLOCK_PENDING_APPROVAL"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class CostEventRecord(ContractModel):
    cost_event_id: int = Field(ge=1)
    task_id: str = Field(min_length=1)
    attempt_id: str | None = None
    channel_id: str = Field(min_length=1)
    billing_mode: str = Field(min_length=1)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    estimated_usd: float = Field(ge=0)
    created_at: datetime


class ApprovalRecord(ContractModel):
    approval_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    payload: dict
    status: ApprovalStatus
    requested_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None


class BudgetAuthorization(ContractModel):
    decision: BudgetDecision
    expected_cost_usd: float = Field(ge=0)
    projected_task_usd: float = Field(ge=0)
    projected_daily_usd: float = Field(ge=0)
    projected_monthly_usd: float = Field(ge=0)
    warning_scopes: tuple[str, ...] = ()
    hard_limit_scopes: tuple[str, ...] = ()
    approval_id: str | None = None
