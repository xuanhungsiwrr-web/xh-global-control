"""Credential-safe health and execution plumbing for subscription CLIs."""

import asyncio
from collections.abc import Awaitable
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import subprocess
import os
from time import monotonic
from uuid import uuid4

from xh_control.models import ChannelHealth

from .base import ChannelRequest, ChannelResponse, ExecutionChannelAdapter
from xh_control.interfaces.processes import terminate_tree

@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str = ""


CommandRunner = Callable[[tuple[str, ...], float], CommandResult | int]
ExecutionRunner = Callable[
    [tuple[str, ...], str, Path, float],
    Awaitable[CommandResult | int],
]


def _run_cli_status(
    command: tuple[str, ...], timeout_seconds: float
) -> CommandResult:
    """Capture status transiently for parsing; never emit it or capture stderr."""
    completed = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=timeout_seconds,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return CommandResult(completed.returncode, completed.stdout)


class CliSubscriptionAdapter(ExecutionChannelAdapter):
    """Probe and invoke one concrete subscription CLI channel."""

    surface: str
    status_command: tuple[str, ...]

    def __init__(
        self,
        *,
        channel_id: str,
        model: str | None = None,
        timeout_seconds: float = 5.0,
        execution_timeout_seconds: float = 900.0,
        output_root: Path | str = Path("runtime/channel-results"),
        command_runner: CommandRunner = _run_cli_status,
        execution_runner: ExecutionRunner | None = None,
        output_id_factory: Callable[[], str] = lambda: uuid4().hex,
    ) -> None:
        if not channel_id:
            raise ValueError("channel_id must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if execution_timeout_seconds <= 0:
            raise ValueError("execution_timeout_seconds must be positive")
        self.channel_id = channel_id
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.execution_timeout_seconds = execution_timeout_seconds
        self.output_root = Path(output_root).resolve()
        self.command_runner = command_runner
        self.execution_runner = execution_runner
        self.output_id_factory = output_id_factory
        self._active_processes: dict[str, asyncio.subprocess.Process] = {}

    async def healthcheck(self) -> dict:
        """Report CLI authentication only; never claim subscription quota health."""
        try:
            raw_result = self.command_runner(self.status_command, self.timeout_seconds)
        except FileNotFoundError:
            health = ChannelHealth.UNAVAILABLE
            reason = "CLI_NOT_FOUND"
        except subprocess.TimeoutExpired:
            health = ChannelHealth.UNKNOWN
            reason = "CLI_STATUS_TIMEOUT"
        except OSError:
            health = ChannelHealth.UNKNOWN
            reason = "CLI_STATUS_ERROR"
        else:
            result = (
                raw_result
                if isinstance(raw_result, CommandResult)
                else CommandResult(returncode=raw_result)
            )
            health, reason = self._interpret_status(result)
        return {
            "channel_id": self.channel_id,
            "surface": self.surface,
            "model": self.model,
            "health": health.value,
            "reason": reason,
            "mechanism": "cli_auth_status",
            "quota_checked": False,
        }

    def _interpret_status(
        self, result: CommandResult
    ) -> tuple[ChannelHealth, str]:
        health = (
            ChannelHealth.AVAILABLE
            if result.returncode == 0
            else ChannelHealth.UNAVAILABLE
        )
        reason = (
            "CLI_AUTHENTICATED"
            if health == ChannelHealth.AVAILABLE
            else "CLI_AUTH_UNAVAILABLE"
        )
        return health, reason

    def _build_execution_command(
        self, request: ChannelRequest, output_path: Path
    ) -> tuple[str, ...]:
        raise NotImplementedError

    def _complete_output(
        self,
        result: CommandResult,
        output_path: Path,
    ) -> dict:
        """Validate/create the result artifact and return truthful reported usage."""
        if not output_path.is_file():
            raise OSError("execution channel did not produce its declared output artifact")
        return {}

    @staticmethod
    def _instruction(request: ChannelRequest) -> str:
        if not request.artifact_refs:
            return request.prompt_or_instruction
        references = "\n".join(f"- {item}" for item in request.artifact_refs)
        return (
            f"{request.prompt_or_instruction}\n\n"
            "Artifact references supplied by the caller (treat as opaque paths/URIs):\n"
            f"{references}"
        )

    async def execute(self, request: ChannelRequest) -> ChannelResponse:
        """Run without blocking the event loop and return an opaque output reference."""
        started = monotonic()
        workspace = Path(request.workspace).resolve()
        if not workspace.is_dir():
            return ChannelResponse(
                success=False,
                output_ref=None,
                usage={},
                latency_seconds=monotonic() - started,
                error_type="WORKSPACE_NOT_FOUND",
            )
        task_directory = sha256(request.task_id.encode("utf-8")).hexdigest()[:24]
        channel_name = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in self.channel_id
        )
        output_path = self.output_root / task_directory / (
            f"{channel_name}-{self.output_id_factory()}.txt"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = self._build_execution_command(request, output_path)
        instruction = self._instruction(request)
        try:
            if self.execution_runner is None:
                raw_result = await self._run_execution_process(
                    request.task_id,
                    command,
                    instruction,
                    workspace,
                    self.execution_timeout_seconds,
                )
            else:
                # Injected runners own their own timeout. Keeping this direct await
                # also permits deterministic I/O-free contract tests on Windows.
                raw_result = await self.execution_runner(
                    command,
                    instruction,
                    workspace,
                    self.execution_timeout_seconds,
                )
            result = (
                raw_result
                if isinstance(raw_result, CommandResult)
                else CommandResult(returncode=raw_result)
            )
        except FileNotFoundError:
            error_type = "CLI_NOT_FOUND"
        except TimeoutError:
            error_type = "CHANNEL_TIMEOUT"
        except (OSError, ValueError):
            error_type = "CHANNEL_OUTPUT_ERROR"
        else:
            if result.returncode != 0:
                error_type = "CHANNEL_PROCESS_FAILED"
            else:
                try:
                    usage = self._complete_output(result, output_path)
                except (OSError, ValueError):
                    error_type = "CHANNEL_OUTPUT_ERROR"
                else:
                    return ChannelResponse(
                        success=True,
                        output_ref=output_path.as_uri(),
                        usage=usage,
                        latency_seconds=monotonic() - started,
                    )
        output_path.unlink(missing_ok=True)
        return ChannelResponse(
            success=False,
            output_ref=None,
            usage={},
            latency_seconds=monotonic() - started,
            error_type=error_type,
        )

    async def _run_execution_process(
        self,
        task_id: str,
        command: tuple[str, ...],
        instruction: str,
        workspace: Path,
        timeout_seconds: float,
    ) -> CommandResult:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=workspace,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=os.name != "nt",
        )
        if task_id in self._active_processes:
            await terminate_tree(process)
            raise ValueError(f"task {task_id} already has an active channel process")
        self._active_processes[task_id] = process
        try:
            stdout, _ = await asyncio.wait_for(
                process.communicate(instruction.encode("utf-8")),
                timeout=timeout_seconds,
            )
        except (TimeoutError, asyncio.CancelledError):
            await terminate_tree(process)
            raise
        finally:
            self._active_processes.pop(task_id, None)
        return CommandResult(
            returncode=process.returncode or 0,
            stdout=stdout.decode("utf-8", errors="replace"),
        )

    async def cancel(self, task_id: str) -> None:
        process = self._active_processes.get(task_id)
        if process is None or process.returncode is not None:
            return
        await terminate_tree(process)
