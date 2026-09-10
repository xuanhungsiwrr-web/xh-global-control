"""Single-process M2 contract flow for one already-persisted plugin task."""

from pydantic import ValidationError

from xh_control.exceptions import PluginResultError, PluginUnavailableError
from xh_control.models import PluginResult, TaskRecord, TaskStatus
from xh_control.plugins import PluginRegistration, PluginRegistry

from .artifact_service import ArtifactService
from .event_service import EventService
from .task_service import TaskService

SUPPORTED_PLUGIN_RESULT_SCHEMA_VERSION = "1.0"
TERMINAL_PLUGIN_RESULT_STATUSES = frozenset(
    {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
)


class PluginExecutionService:
    """Run the M2 plugin boundary without routing or domain interpretation."""

    def __init__(
        self,
        task_service: TaskService,
        event_service: EventService,
        artifact_service: ArtifactService,
        plugin_registry: PluginRegistry,
    ) -> None:
        self.task_service = task_service
        self.event_service = event_service
        self.artifact_service = artifact_service
        self.plugin_registry = plugin_registry

    async def execute(self, task_id: str) -> PluginResult:
        """Execute a mockable plugin and persist only contract-approved output."""
        task = self.task_service.get_task(task_id).task
        registration = self.plugin_registry.resolve_for_task(task)
        try:
            healthy = await registration.adapter.healthcheck()
        except Exception:
            self._reject(task_id, registration, "healthcheck_error")
            raise PluginUnavailableError(
                f"Plugin healthcheck failed for task {task_id}"
            ) from None
        if not healthy:
            self._reject(task_id, registration, "unavailable")
            raise PluginUnavailableError(f"Plugin unavailable for task {task_id}")

        self._start(task_id)
        self.event_service.append(
            task_id,
            "PLUGIN_EXECUTION_STARTED",
            {
                "plugin_id": registration.manifest.plugin_id,
                "interface_version": registration.manifest.interface_version,
            },
        )
        try:
            raw_result = await registration.adapter.execute(task)
        except Exception:
            self._reject(task_id, registration, "execution_error")
            raise PluginResultError(f"Plugin execution failed for task {task_id}") from None

        try:
            payload = (
                raw_result.model_dump(mode="python")
                if isinstance(raw_result, PluginResult)
                else raw_result
            )
            result = PluginResult.model_validate(payload)
            target = self._validate_result(task_id, result, registration)
        except (ValidationError, ValueError, PluginResultError):
            self._reject(task_id, registration, "invalid_contract")
            raise PluginResultError(
                f"Plugin result rejected for task {task_id}: invalid contract"
            ) from None

        for output in result.outputs:
            self.artifact_service.register(
                task_id,
                output.artifact_type,
                output.uri,
                sha256=output.sha256,
            )
        self.event_service.append(
            task_id,
            "PLUGIN_RESULT_ACCEPTED",
            {
                "plugin_id": registration.manifest.plugin_id,
                "status": target.value,
                "output_count": len(result.outputs),
                "elapsed_seconds": result.execution_summary.elapsed_seconds,
                "api_spend_usd": result.execution_summary.api_spend_usd,
            },
        )
        self.task_service.transition_task(task_id, target)
        return result

    def _start(self, task_id: str) -> TaskRecord:
        record = self.task_service.get_task(task_id)
        if record.status != TaskStatus.CREATED:
            raise PluginResultError(
                f"Plugin execution requires CREATED task, got {record.status.value}"
            )
        for target in (TaskStatus.QUEUED, TaskStatus.ASSIGNED, TaskStatus.RUNNING):
            record = self.task_service.transition_task(task_id, target)
        return record

    @staticmethod
    def _validate_result(
        task_id: str,
        result: PluginResult,
        registration: PluginRegistration,
    ) -> TaskStatus:
        if result.schema_version != SUPPORTED_PLUGIN_RESULT_SCHEMA_VERSION:
            raise PluginResultError("unsupported plugin result schema")
        if result.task_id != task_id:
            raise PluginResultError("plugin result belongs to another task")
        try:
            target = TaskStatus(result.status)
        except ValueError:
            raise PluginResultError("unknown plugin result status") from None
        if target not in TERMINAL_PLUGIN_RESULT_STATUSES:
            raise PluginResultError("execute must return a terminal plugin result")
        used_learning_fields = {
            field_name
            for field_name in type(result.global_learning).model_fields
            if getattr(result.global_learning, field_name)
        }
        if not used_learning_fields <= registration.manifest.allowed_global_learning_fields:
            raise PluginResultError("plugin returned a disallowed global learning category")
        return target

    def _reject(
        self,
        task_id: str,
        registration: PluginRegistration,
        reason: str,
    ) -> None:
        """Persist a reason code only; never persist rejected plugin content."""
        event_type = (
            "PLUGIN_RESULT_REJECTED"
            if reason == "invalid_contract"
            else "PLUGIN_EXECUTION_FAILED"
        )
        record = self.task_service.get_task(task_id)
        if record.status not in {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }:
            self.event_service.append(
                task_id,
                event_type,
                {"plugin_id": registration.manifest.plugin_id, "reason": reason},
            )
            self.task_service.transition_task(task_id, TaskStatus.FAILED)
