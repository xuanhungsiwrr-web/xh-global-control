"""Task envelope and runtime-record contracts."""

from datetime import datetime

from pydantic import Field, model_validator

from .base import ContractModel
from .enums import CostMode, FailureType, MasterPreference, PermissionLevel, TaskStatus


class ProjectRef(ContractModel):
    project_id: str = Field(min_length=1)
    workspace_uri: str = Field(min_length=1)


class TaskBudget(ContractModel):
    api_soft_usd: float = Field(ge=0)
    api_hard_usd: float = Field(ge=0)

    @model_validator(mode="after")
    def hard_limit_is_not_below_soft_limit(self) -> "TaskBudget":
        if self.api_hard_usd < self.api_soft_usd:
            raise ValueError("api_hard_usd must be greater than or equal to api_soft_usd")
        return self


class ExecutionRequest(ContractModel):
    master_capability: str = Field(default="MASTER", min_length=1)
    master_preference: MasterPreference = MasterPreference.AUTO
    cost_mode: CostMode = CostMode.BALANCED


class PermissionRequest(ContractModel):
    level: PermissionLevel = PermissionLevel.SAFE_EDIT


class TaskEnvelope(ContractModel):
    schema_version: str = "1.0"
    task_id: str = Field(min_length=1)
    created_at: datetime
    task_type: str = Field(min_length=1)
    plugin: str = Field(min_length=1)
    report_type: str | None = None
    project: ProjectRef
    execution: ExecutionRequest
    permissions: PermissionRequest
    budget: TaskBudget
    user_request: str = Field(min_length=1)


class TaskRecord(ContractModel):
    task: TaskEnvelope
    status: TaskStatus
    assigned_worker: str | None = None
    resolved_channel: str | None = None
    current_attempt_id: str | None = None
    latest_checkpoint_uri: str | None = None


class ExecutionAttemptRecord(ContractModel):
    attempt_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    attempt_no: int = Field(ge=1)
    worker_id: str = Field(min_length=1)
    channel_id: str | None = None
    status: TaskStatus
    failure_type: FailureType | None = None
    failure_message: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    generation: int = Field(ge=1)


class TaskEventRecord(ContractModel):
    event_id: int = Field(ge=1)
    task_id: str = Field(min_length=1)
    attempt_id: str | None = None
    event_type: str = Field(min_length=1)
    payload: dict
    created_at: datetime
