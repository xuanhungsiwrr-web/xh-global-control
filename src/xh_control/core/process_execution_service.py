"""Compose M4 services for an approved, trusted process plugin.

No domain prompts, source parsing, or report decisions belong here.
"""

from pathlib import Path
import sys

from xh_control.channels import ChannelRequest
from xh_control.channels.factory import ChannelAdapterFactory
from xh_control.channels.codex import CodexAdapter
from xh_control.config import Configuration
from xh_control.exceptions import PluginResultError, PluginUnavailableError
from xh_control.learning import OperationalMetricsService
from xh_control.models import (ChannelClass, ChannelHealth, TaskEnvelope, TaskStatus,
                               PluginResult, ExecutionAttemptRecord)
from xh_control.permissions import PermissionPolicy
from xh_control.plugins import PluginRegistry
from xh_control.plugins.process_adapter import ProcessPluginAdapter
from xh_control.plugins.factory import bind_process_plugin
from xh_control.routing.channel_router import ChannelRouter
from xh_control.state import (TaskRepository, EventRepository, ArtifactRepository,
                             CostRepository, GlobalLearningRepository, initialize_database)
from xh_control.workers.selector import WorkerSelector
from .task_service import TaskService
from .event_service import EventService
from .artifact_service import ArtifactService
from .checkpoint_service import CheckpointService
from .channel_execution_service import ChannelExecutionService
from .channel_execution_service import AdapterFactory


class ProcessExecutionService:
    def __init__(self, configuration: Configuration, *, adapter_factory: AdapterFactory | None = None) -> None:
        self.configuration = configuration
        self.database = initialize_database(configuration)
        self.tasks = TaskService(TaskRepository(self.database))
        self.events = EventService(EventRepository(self.database))
        self.artifacts = ArtifactService(ArtifactRepository(self.database))
        self.checkpoint_service = CheckpointService(self.artifacts)
        self.metrics = OperationalMetricsService(CostRepository(self.database), GlobalLearningRepository(self.database))
        self.factory = adapter_factory or ChannelAdapterFactory(configuration).create
        self.active: dict[str, ProcessPluginAdapter] = {}

    async def execute(self, task: TaskEnvelope) -> PluginResult:
        if task.task_id in self.active:
            raise PluginResultError("task already executing")
        manifest = self.configuration.plugins.get(task.plugin)
        if manifest is None or manifest.entrypoint_type != "process":
            raise PluginUnavailableError("configured process plugin required")
        executable = Path(manifest.entrypoint)
        if not executable.is_absolute() or not executable.is_file():
            raise PluginUnavailableError("absolute trusted process entrypoint is unavailable")
        PermissionPolicy(self.configuration.permissions).validate(task)
        worker = WorkerSelector(self.configuration.workers).select(manifest.required_global_capabilities)
        # Health probe every eligible subscription; never select paid execution in M4.
        channels, adapters = {}, {}
        for key, channel in self.configuration.channels.items():
            if not channel.enabled or channel.channel_class != ChannelClass.SUBSCRIPTION:
                continue
            surface_capability = {"codex": "codex", "claude_code": "claude_code"}.get(channel.surface)
            if surface_capability not in self.configuration.workers[worker].capabilities:
                continue
            adapter = self.factory(task, channel)
            if isinstance(adapter, CodexAdapter):
                adapter.isolated_tools = True
            health = await adapter.healthcheck()
            channels[key] = channel.model_copy(update={"health": ChannelHealth(health["health"])})
            adapters[key] = adapter
        config = self.configuration.model_copy(update={"channels": channels})
        channel = ChannelRouter(config).resolve_master_channel(task=task, worker_id=worker)
        adapter = adapters[channel.channel_id]
        self.tasks.create_task(task)
        attempt = self.tasks.create_attempt(task.task_id, worker, channel.channel_id)
        context = {
            "task_id": task.task_id, "attempt_id": attempt.attempt_id,
            "generation": attempt.generation, "worker_id": worker,
            "channel_id": channel.channel_id,
            "permissions": task.permissions.model_dump(mode="json"),
            "budget": task.budget.model_dump(mode="json"),
        }
        channel_service = ChannelExecutionService(
            self.tasks, self.events, self.artifacts, self.metrics, channels,
            lambda bound_task, bound_channel: adapter,
        )

        async def invoke(request: ChannelRequest):
            # Revalidate permissions and envelope; binding cannot be changed by IPC.
            current = self.tasks.get_task(task.task_id)
            if current.task != task:
                raise PluginResultError("task grant changed")
            PermissionPolicy(self.configuration.permissions).validate(current.task)
            response = await channel_service.execute(
                task_id=task.task_id, attempt_id=attempt.attempt_id,
                generation=attempt.generation, request=request,
            )
            self.tasks.validate_fence(task.task_id, attempt.attempt_id, attempt.generation)
            return response

        transport = ProcessPluginAdapter(
            (sys.executable, str(executable)), context,
            self.configuration.artifact_path / "transport",
            invoke, adapter.cancel,
        )
        registry = PluginRegistry()
        plugin = bind_process_plugin(manifest.plugin_id, transport)
        registry.register(manifest, plugin)
        self.active[task.task_id] = transport
        try:
            registry.resolve_for_task(task)
            if not await plugin.healthcheck():
                raise PluginUnavailableError("plugin wrapper healthcheck failed")
            for state in (TaskStatus.QUEUED, TaskStatus.ASSIGNED, TaskStatus.RUNNING):
                self.tasks.transition_task(task.task_id, state)
            self.tasks.transition_attempt(task.task_id, attempt.attempt_id, attempt.generation, TaskStatus.RUNNING)
            self.events.append(task.task_id, "PLUGIN_EXECUTION_STARTED", {"plugin_id": task.plugin}, attempt_id=attempt.attempt_id)
            result = await plugin.execute(task)
            if task.task_id in transport.cancelled:
                raise PluginResultError("PLUGIN_CANCELLED")
            target = TaskStatus(result.status)
            used_fields = {name for name in type(result.global_learning).model_fields
                           if getattr(result.global_learning, name)}
            if not used_fields <= manifest.allowed_global_learning_fields:
                raise PluginResultError("disallowed global learning category")
            self.tasks.validate_fence(task.task_id, attempt.attempt_id, attempt.generation)
            for output in result.outputs:
                path = ChannelExecutionService._local_file(output.uri)
                from hashlib import sha256
                if path is None or sha256(path.read_bytes()).hexdigest() != output.sha256:
                    raise PluginResultError("plugin artifact hash mismatch")
                self.artifacts.register(task.task_id, output.artifact_type, output.uri,
                                        sha256=output.sha256, attempt_id=attempt.attempt_id)
            self.events.append(task.task_id, "PLUGIN_RESULT_ACCEPTED",
                               {"plugin_id": task.plugin, "status": target.value, "output_count": len(result.outputs)},
                               attempt_id=attempt.attempt_id)
            self._finish(task.task_id, attempt, target)
            return result
        except BaseException:
            # Cancellation is a confirmed execution abort; M5 safe-stop/handoff is separate.
            target = TaskStatus.FAILED
            self.events.append(task.task_id, "PLUGIN_EXECUTION_FAILED", {"reason": "execution_aborted"}, attempt_id=attempt.attempt_id)
            self._finish(task.task_id, attempt, target)
            raise
        finally:
            self.active.pop(task.task_id, None)

    def _finish(self, task_id: str, attempt: ExecutionAttemptRecord, target: TaskStatus) -> None:
        self.tasks.transition_attempt(task_id, attempt.attempt_id, attempt.generation, target)
        self.tasks.transition_task(task_id, target, attempt_id=attempt.attempt_id, generation=attempt.generation)

    async def cancel(self, task_id: str) -> None:
        transport = self.active.get(task_id)
        if transport:
            await transport.cancel(task_id)

    async def pause(self, task_id: str) -> None:
        """Request a plugin-owned safe pause, then persist the Global checkpoint."""
        task = self.tasks.get_task(task_id)
        PermissionPolicy(self.configuration.permissions).validate(task.task)
        if task.status != TaskStatus.RUNNING or task.current_attempt_id is None:
            raise PluginUnavailableError("task is not an active resumable execution")
        transport = self.active.get(task_id)
        if transport is None:
            raise PluginUnavailableError("active plugin process is unavailable")
        await transport.pause(task_id)
        attempt = self.tasks.get_attempt(task.current_attempt_id)
        refs = [item.uri for item in self.artifacts.list_for_task(task_id)]
        self.checkpoint_service.create(
            task, attempt_id=attempt.attempt_id, generation=attempt.generation,
            worker_id=attempt.worker_id, channel_id=attempt.channel_id,
            plugin_state_ref="opaque://plugin-state/pause", artifact_refs=refs,
        )
        self.tasks.transition_task(task_id, TaskStatus.PAUSED,
                                   attempt_id=attempt.attempt_id, generation=attempt.generation)

    async def resume(self, task_id: str) -> None:
        """Validate the durable checkpoint before handing control to a plugin resume transport."""
        task = self.tasks.get_task(task_id)
        PermissionPolicy(self.configuration.permissions).validate(task.task)
        if task.status != TaskStatus.PAUSED:
            raise PluginResultError("task is not PAUSED")
        checkpoint = self.checkpoint_service.load(task)
        if task_id in self.active:
            raise PluginResultError("task already executing")
        # The current process protocol has no restart-safe resume verb yet.
        # Refusing here is safer than replaying user history or duplicating an
        # uncertain external side effect.
        raise PluginUnavailableError(
            f"resume transport is not implemented for checkpoint revision {checkpoint.revision}"
        )
