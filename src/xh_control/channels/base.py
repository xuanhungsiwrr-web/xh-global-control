"""Execution-channel adapter contract from MVP Specification section 9."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ChannelRequest:
    task_id: str
    capability: str
    prompt_or_instruction: str
    workspace: str
    artifact_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ChannelResponse:
    success: bool
    output_ref: str | None
    usage: dict
    latency_seconds: float
    error_type: str | None = None


class ExecutionChannelAdapter(ABC):
    @abstractmethod
    async def healthcheck(self) -> dict:
        ...

    @abstractmethod
    async def execute(self, request: ChannelRequest) -> ChannelResponse:
        ...

    @abstractmethod
    async def cancel(self, task_id: str) -> None:
        ...
