"""Fenced execution through the already-resolved subscription channel."""

from collections.abc import Callable, Mapping
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlparse

from xh_control.channels import ChannelRequest, ChannelResponse, ExecutionChannelAdapter
from xh_control.exceptions import BudgetStateError, ChannelError, StateConflictError
from xh_control.learning import OperationalMetricsService
from xh_control.models import ChannelClass, ExecutionChannel, TaskEnvelope, TaskStatus

from .artifact_service import ArtifactService
from .event_service import EventService
from .task_service import TaskService


AdapterFactory = Callable[[TaskEnvelope, ExecutionChannel], ExecutionChannelAdapter]


class ChannelExecutionService:
    """Execute only the channel assigned to the current fenced attempt."""

    def __init__(
        self,
        task_service: TaskService,
        event_service: EventService,
        artifact_service: ArtifactService,
        metrics_service: OperationalMetricsService,
        channels: Mapping[str, ExecutionChannel],
        adapter_factory: AdapterFactory,
    ) -> None:
        self.task_service = task_service
        self.event_service = event_service
        self.artifact_service = artifact_service
        self.metrics_service = metrics_service
        self.channels = dict(channels)
        self.adapter_factory = adapter_factory

    async def execute(
        self,
        *,
        task_id: str,
        attempt_id: str,
        generation: int,
        request: ChannelRequest,
    ) -> ChannelResponse:
        task_record = self.task_service.get_task(task_id)
        attempt = self.task_service.validate_fence(task_id, attempt_id, generation)
        if task_record.status != TaskStatus.RUNNING or attempt.status != TaskStatus.RUNNING:
            raise StateConflictError("channel execution requires a RUNNING task and attempt")
        if request.task_id != task_id:
            raise StateConflictError("channel request belongs to another task")
        if request.capability != task_record.task.execution.master_capability:
            raise ChannelError("channel request capability does not match TaskEnvelope")
        if request.workspace != task_record.task.project.workspace_uri:
            raise ChannelError("channel request workspace does not match TaskEnvelope")
        if not attempt.channel_id or attempt.channel_id not in self.channels:
            raise ChannelError("attempt has no configured execution channel")
        channel = self.channels[attempt.channel_id]
        if channel.channel_class != ChannelClass.SUBSCRIPTION:
            raise BudgetStateError(
                "M4 channel execution accepts subscription channels only; paid execution "
                "must be authorized by BudgetEngine first"
            )
        if request.capability not in channel.capabilities:
            raise ChannelError("assigned channel lacks the requested capability")

        adapter = self.adapter_factory(task_record.task, channel)
        response = await adapter.execute(request)
        self.task_service.validate_fence(task_id, attempt_id, generation)
        if self.task_service.get_task(task_id).status != TaskStatus.RUNNING:
            raise StateConflictError("task stopped while channel was executing")
        artifact_id = None
        if response.success:
            if not response.output_ref:
                raise ChannelError("successful channel response has no output reference")
            file_path = self._local_file(response.output_ref)
            digest = None
            size_bytes = None
            if file_path is not None and file_path.is_file():
                content = file_path.read_bytes()
                digest = sha256(content).hexdigest()
                size_bytes = len(content)
            artifact = self.artifact_service.register(
                task_id,
                "channel-output",
                response.output_ref,
                attempt_id=attempt_id,
                sha256=digest,
                size_bytes=size_bytes,
            )
            artifact_id = artifact.artifact_id

        metric = self.metrics_service.record_channel_response(
            task_id=task_id,
            attempt_id=attempt_id,
            plugin_id=task_record.task.plugin,
            capability=request.capability,
            channel=channel,
            response=response,
        )
        self.event_service.append(
            task_id,
            "CHANNEL_EXECUTION_FINISHED",
            {
                "channel_id": channel.channel_id,
                "success": response.success,
                "error_type": response.error_type,
                "artifact_id": artifact_id,
                "learning_event_id": metric.learning_event_id,
            },
            attempt_id=attempt_id,
        )
        return response

    @staticmethod
    def _local_file(uri: str) -> Path | None:
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            return None
        path = unquote(parsed.path)
        if parsed.netloc:
            path = f"//{parsed.netloc}{path}"
        elif len(path) >= 3 and path[0] == "/" and path[2] == ":":
            path = path[1:]
        return Path(path)
