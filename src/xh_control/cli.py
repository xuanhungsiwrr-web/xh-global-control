"""Offline configuration and M1 task-core commands."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from . import __version__
from .config import load_config
from .core.identifiers import new_task_id
from .core.task_service import TaskService
from .exceptions import XHControlError
from .models import (
    CostMode,
    ExecutionRequest,
    MasterPreference,
    PermissionLevel,
    PermissionRequest,
    ProjectRef,
    TaskBudget,
    TaskEnvelope,
)
from .state import TaskRepository, initialize_database

app = typer.Typer(no_args_is_help=True)
ConfigRoot = Annotated[Path | None, typer.Option(help="Configuration directory; defaults to repository/config.")]


@app.command()
def validate_config(config_root: ConfigRoot = None) -> None:
    """Validate every expected YAML configuration file offline."""
    try:
        config = load_config(config_root)
    except XHControlError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(f"Configuration valid: {config.config_root} (8 files)")


@app.command()
def db_init(config_root: ConfigRoot = None) -> None:
    """Idempotently initialize the SQLite database configured in system.yaml."""
    try:
        path = initialize_database(load_config(config_root))
    except XHControlError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(f"SQLite initialized: {path}")


@app.command()
def version() -> None:
    """Show the package version."""
    typer.echo(__version__)


@app.command("run")
def run_task(
    plugin: Annotated[str, typer.Option(help="Owning domain plugin identifier.")],
    project: Annotated[str, typer.Option(help="Opaque project identifier.")],
    task: Annotated[str, typer.Option(help="Opaque request passed to the plugin.")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Persist task state without execution.")] = False,
    task_type: Annotated[str, typer.Option(help="Opaque task type.")] = "generic",
    workspace_uri: Annotated[str | None, typer.Option(help="Project workspace reference.")] = None,
    report_type: Annotated[str | None, typer.Option(help="Optional opaque report type.")] = None,
    master: Annotated[MasterPreference | None, typer.Option(help="Logical Master preference.")] = None,
    mode: Annotated[CostMode | None, typer.Option(help="Task cost mode.")] = None,
    permission: Annotated[PermissionLevel | None, typer.Option(help="Requested permission level.")] = None,
    task_id: Annotated[str | None, typer.Option(help="Caller-supplied task identifier.")] = None,
    config_root: ConfigRoot = None,
) -> None:
    """Create an M1 task and audit trail; execution remains deferred."""
    if not dry_run:
        typer.echo("M1 supports task creation only with --dry-run", err=True)
        raise typer.Exit(2)
    try:
        config = load_config(config_root)
        database_path = initialize_database(config)
        now = datetime.now(UTC)
        configured_budget = config.budgets.plugins.get(plugin, config.budgets.defaults)
        envelope = TaskEnvelope(
            task_id=task_id or new_task_id(now),
            created_at=now,
            task_type=task_type,
            plugin=plugin,
            report_type=report_type,
            project=ProjectRef(project_id=project, workspace_uri=workspace_uri or project),
            execution=ExecutionRequest(
                master_preference=master or config.system.default_master,
                cost_mode=mode or config.system.default_cost_mode,
            ),
            permissions=PermissionRequest(
                level=permission or config.permissions.default_level
            ),
            budget=TaskBudget(
                api_soft_usd=configured_budget.task_api_soft_usd,
                api_hard_usd=configured_budget.task_api_hard_usd,
            ),
            user_request=task,
        )
        record = TaskService(TaskRepository(database_path)).create_task(envelope)
    except (XHControlError, ValidationError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(f"Task created: {record.task.task_id}")
    typer.echo(f"Plugin: {record.task.plugin}")
    typer.echo(f"Project: {record.task.project.project_id}")
    typer.echo(f"Master: {record.task.execution.master_preference.value}")
    typer.echo(f"Mode: {record.task.execution.cost_mode.value}")
    typer.echo(f"Status: {record.status.value}")
    typer.echo("Audit events: 1")
    typer.echo("Dry run: no plugin or execution channel was invoked")


if __name__ == "__main__":
    app()
