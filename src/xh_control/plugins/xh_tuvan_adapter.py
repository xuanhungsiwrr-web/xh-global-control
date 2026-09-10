"""xh-tuvan facade for the approved ACR-001 process transport."""

from xh_control.exceptions import PluginUnavailableError
from xh_control.models import PluginResult, TaskEnvelope

from .base import DomainPluginAdapter
from .process_adapter import ProcessPluginAdapter


class XHTuvanAdapter(DomainPluginAdapter):
    """Delegate execution to the bound transport; keep domain workflow external."""

    _BLOCKER = (
        "xh-tuvan requires a bound task-scoped process transport; see ACR-001"
    )

    def __init__(self, transport: ProcessPluginAdapter | None = None) -> None:
        self.transport = transport

    async def healthcheck(self) -> bool:
        return await self.transport.healthcheck() if self.transport else False

    async def execute(self, task: TaskEnvelope) -> PluginResult:
        if self.transport:
            return await self.transport.execute(task)
        raise PluginUnavailableError(self._BLOCKER)

    async def pause(self, task_id: str) -> str:
        if self.transport:
            return await self.transport.pause(task_id)
        raise PluginUnavailableError(self._BLOCKER)

    async def resume(self, task: TaskEnvelope, handoff_uri: str) -> PluginResult:
        if self.transport:
            return await self.transport.resume(task, handoff_uri)
        raise PluginUnavailableError(self._BLOCKER)

    async def cancel(self, task_id: str) -> None:
        if self.transport:
            return await self.transport.cancel(task_id)
        raise PluginUnavailableError(self._BLOCKER)
