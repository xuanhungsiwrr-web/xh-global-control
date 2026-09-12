"""Global Control orchestration behind Telegram and future UI adapters."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import logging
from pathlib import Path
import re
from typing import Any

from xh_control.config import Configuration
from xh_control.core.identifiers import new_task_id
from xh_control.exceptions import PluginUnavailableError
from xh_control.interfaces.telegram import TelegramCommand, TelegramCommandError, TelegramUpdate
from xh_control.models import (
    ApprovalStatus,
    CostMode,
    ExecutionRequest,
    MasterPreference,
    PermissionLevel,
    PermissionRequest,
    ProjectRef,
    TaskBudget,
    TaskEnvelope,
)

logger = logging.getLogger(__name__)


class GlobalController:
    """Own command semantics; Telegram remains a thin input/output adapter."""

    def __init__(self, configuration: Configuration, *, task_service, execution_service=None,
                 cost_repository=None, approval_repository=None, checkpoint_service=None) -> None:
        self.configuration = configuration
        self.task_service = task_service
        self.execution_service = execution_service
        self.cost_repository = cost_repository
        self.approval_repository = approval_repository
        self.checkpoint_service = checkpoint_service or getattr(execution_service, "checkpoint_service", None)
        self._preferences: dict[str, tuple[MasterPreference, CostMode]] = {}
        self._background: set[asyncio.Task[Any]] = set()

    async def handle_telegram_command(self, command: TelegramCommand, update: TelegramUpdate) -> str:
        try:
            method = getattr(self, f"_command_{command.name}")
            return await method(command, update)
        except Exception:
            logger.exception(
                "Telegram command execution failed: command=%r update_id=%r user_id=%r chat_id=%r",
                command, update.update_id, update.user_id, update.chat_id,
            )
            raise

    async def _command_run(self, command: TelegramCommand, update: TelegramUpdate) -> str:
        master, mode = self._preferences.get(update.user_id, (
            self.configuration.system.default_master,
            self.configuration.system.default_cost_mode,
        ))
        master = self._master(command.option("master", master.value))
        mode = self._mode(command.option("mode", mode.value))
        plugin = command.option("plugin")
        project = command.option("project")
        request = command.option("task")
        assert plugin is not None and project is not None and request is not None
        configured_budget = self.configuration.budgets.plugins.get(plugin, self.configuration.budgets.defaults)
        envelope = TaskEnvelope(
            task_id=new_task_id(datetime.now(UTC)),
            created_at=datetime.now(UTC),
            task_type=command.option("task_type", "generic") or "generic",
            plugin=plugin,
            report_type=command.option("report_type"),
            project=ProjectRef(
                project_id=project,
                workspace_uri=self._workspace_uri(
                    project,
                    command.option("workspace"),
                    resolve_alias=self.execution_service is not None,
                ),
            ),
            execution=ExecutionRequest(master_preference=master, cost_mode=mode),
            permissions=PermissionRequest(level=self._permission(command.option("permission", "SAFE_EDIT"))),
            budget=TaskBudget(api_soft_usd=configured_budget.task_api_soft_usd, api_hard_usd=configured_budget.task_api_hard_usd),
            user_request=request,
        )
        if self.execution_service is None:
            record = self.task_service.create_task(envelope)
            return self._summary(record)
        # The loopback HTTP adapter owns one request loop per update; await the
        # bounded execution so no task is orphaned when that loop closes.
        await self.execution_service.execute(envelope)
        return self._summary(self.task_service.get_task(envelope.task_id))

    async def _command_status(self, command, update):
        return self._summary(self.task_service.get_task(command.positionals[0]))

    async def _command_tasks(self, command, update):
        records = self.task_service.list_tasks()
        if not records:
            return "No tasks."
        return "\n".join(f"{item.task.task_id}  {item.status.value}  {item.task.plugin}" for item in records)

    async def _command_master(self, command, update):
        _, mode = self._preferences.get(update.user_id, (self.configuration.system.default_master, self.configuration.system.default_cost_mode))
        master = self._master(command.positionals[0])
        self._preferences[update.user_id] = (master, mode)
        return f"Default master: {master.value}"

    async def _command_mode(self, command, update):
        master, _ = self._preferences.get(update.user_id, (self.configuration.system.default_master, self.configuration.system.default_cost_mode))
        mode = self._mode(command.positionals[0])
        self._preferences[update.user_id] = (master, mode)
        return f"Default mode: {mode.value}"

    async def _command_cost(self, command, update):
        if self.cost_repository is None:
            return "Cost service unavailable."
        task_id = command.positionals[0] if command.positionals else None
        value = self.cost_repository.sum_estimated(task_id=task_id)
        return f"Estimated API cost{f' for {task_id}' if task_id else ''}: ${value:.4f}"

    async def _command_pause(self, command, update):
        task_id = command.positionals[0]
        if self.execution_service is not None and hasattr(self.execution_service, "pause"):
            await self.execution_service.pause(task_id)
        else:
            self.task_service.get_task(task_id)
            raise PluginUnavailableError("pause requires an execution service")
        return f"Paused: {task_id}"

    async def _command_resume(self, command, update):
        task_id = command.positionals[0]
        if self.execution_service is not None and hasattr(self.execution_service, "resume"):
            await self.execution_service.resume(task_id)
        else:
            self.task_service.get_task(task_id)
            raise PluginUnavailableError("resume requires an execution service")
        return f"Resume queued: {task_id}"

    async def _command_stop(self, command, update):
        if self.execution_service is None:
            return "Execution service unavailable."
        await self.execution_service.cancel(command.positionals[0])
        return f"Stop requested: {command.positionals[0]}"

    async def _command_approve(self, command, update):
        if self.approval_repository is None:
            return "Approval service unavailable."
        approval = self.approval_repository.decide(command.positionals[0], ApprovalStatus.APPROVED, update.user_id)
        return f"Approved: {approval.approval_id}"

    async def _command_deny(self, command, update):
        if self.approval_repository is None:
            return "Approval service unavailable."
        approval = self.approval_repository.decide(command.positionals[0], ApprovalStatus.DENIED, update.user_id)
        return f"Denied: {approval.approval_id}"

    async def _active_action(self, task_id: str, action: str) -> str:
        active = getattr(self.execution_service, "active", {}).get(task_id) if self.execution_service else None
        if active is None:
            return f"Task is not actively executing: {task_id}"
        try:
            result = await getattr(active, action)(task_id)
        except Exception as exc:
            return f"/{action} unavailable: {type(exc).__name__}"
        return f"{action.title()} requested: {task_id}" if result is None else str(result)

    @staticmethod
    def _master(value: str) -> MasterPreference:
        return {"auto": MasterPreference.AUTO, "claude": MasterPreference.CLAUDE, "chatgpt": MasterPreference.CHATGPT}[value.lower()]

    @staticmethod
    def _mode(value: str) -> CostMode:
        return {"economy": CostMode.ECONOMY, "balanced": CostMode.BALANCED, "max": CostMode.MAX_QUALITY, "max_quality": CostMode.MAX_QUALITY}[value.lower()]

    @staticmethod
    def _permission(value: str) -> PermissionLevel:
        return PermissionLevel(value.upper())

    def _workspace_uri(self, project: str, explicit: str | None, *, resolve_alias: bool) -> str:
        if explicit:
            return explicit
        if not resolve_alias:
            return project

        supplied = Path(project)
        if supplied.is_absolute() and supplied.is_dir():
            return str(supplied.resolve())

        alias = re.sub(r"[^a-z0-9]", "", project.lower())
        matches: dict[str, Path] = {}
        if len(alias) >= 4:
            for worker in self.configuration.workers.values():
                if not worker.enabled:
                    continue
                root = Path(worker.paths.project_root)
                if not root.is_dir():
                    continue
                for candidate in root.iterdir():
                    normalized = re.sub(r"[^a-z0-9]", "", candidate.name.lower())
                    if candidate.is_dir() and alias in normalized:
                        resolved = candidate.resolve()
                        matches[str(resolved).casefold()] = resolved
        if len(matches) == 1:
            return str(next(iter(matches.values())))
        if len(matches) > 1:
            raise TelegramCommandError(
                f"Project alias is ambiguous: {project}. Pass workspace=<absolute path>."
            )
        raise TelegramCommandError(
            f"Project workspace not found: {project}. Pass workspace=<absolute path>."
        )

    @staticmethod
    def _summary(record) -> str:
        task = record.task
        return (f"Task: {task.task_id}\nStatus: {record.status.value}\nWorker: {record.assigned_worker or 'pending'}\n"
                f"Channel: {record.resolved_channel or 'pending'}\nPlugin: {task.plugin}")
