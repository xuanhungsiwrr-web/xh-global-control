"""Interface implemented by every domain-plugin adapter."""

from abc import ABC, abstractmethod

from xh_control.models import PluginResult, TaskEnvelope


class DomainPluginAdapter(ABC):
    """Keep domain workflow behind a small, replaceable async contract."""

    @abstractmethod
    async def healthcheck(self) -> bool:
        ...

    @abstractmethod
    async def execute(self, task: TaskEnvelope) -> PluginResult:
        ...

    @abstractmethod
    async def pause(self, task_id: str) -> None:
        ...

    @abstractmethod
    async def resume(self, task_id: str) -> PluginResult:
        ...

    @abstractmethod
    async def cancel(self, task_id: str) -> None:
        ...
