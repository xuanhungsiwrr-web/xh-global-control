"""ACR-001 process transport with one task-scoped channel invocation."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from xh_control.channels import ChannelRequest, ChannelResponse
from xh_control.exceptions import PluginResultError, PluginUnavailableError
from xh_control.interfaces.channel_bridge import MAX_MESSAGE, publish, read_message
from xh_control.interfaces.processes import terminate_tree
from xh_control.models import PluginResult, TaskEnvelope
from .base import DomainPluginAdapter


class ProcessPluginAdapter(DomainPluginAdapter):
    """Trusted local plugin code; transport is not an OS sandbox for plugins.

    Context values are a snapshot only: the injected Global callback revalidates
    the authoritative SQLite fence and the granted channel policy on every call.
    """

    def __init__(
        self, command: tuple[str, ...], context: dict, runtime_root: Path,
        execute_channel: Callable[[ChannelRequest], Awaitable[ChannelResponse]],
        cancel_channel: Callable[[str], Awaitable[None]],
        *, timeout_seconds: float = 900,
    ) -> None:
        self.command = command
        self.context = dict(context)
        self.runtime_root = runtime_root.resolve()
        self.execute_channel = execute_channel
        self.cancel_channel = cancel_channel
        self.timeout_seconds = timeout_seconds
        self.active: dict[str, asyncio.subprocess.Process] = {}
        self.cancelled: set[str] = set()

    async def healthcheck(self) -> bool:
        try:
            process = await asyncio.create_subprocess_exec(
                *self.command, "--healthcheck", stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, start_new_session=os.name != "nt",
            )
        except OSError:
            return False
        try:
            output, _ = await asyncio.wait_for(process.communicate(), 10)
            health = json.loads(output)
            return process.returncode == 0 and health == {
                "protocol_version": "1.0", "healthy": True,
            }
        except (ValueError, TimeoutError):
            await terminate_tree(process)
            return False
        except asyncio.CancelledError:
            await terminate_tree(process)
            raise

    async def execute(self, task: TaskEnvelope) -> PluginResult:
        if task.task_id in self.active:
            raise PluginResultError("task already executing")
        if task.task_id != self.context["task_id"]:
            raise PluginResultError("task does not match bound context")
        directory = self.runtime_root / uuid4().hex
        directory.mkdir(parents=True)
        context = self.context | {
            "protocol_version": "1.0",
            "channel_bridge": [sys.executable, "-m", "xh_control.interfaces.channel_bridge"],
            "timeout_seconds": self.timeout_seconds,
        }
        publish(directory / "context.json", context)
        process = await asyncio.create_subprocess_exec(
            *self.command, "--context", str(directory / "context.json"),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, start_new_session=os.name != "nt",
        )
        self.active[task.task_id] = process
        communication = asyncio.create_task(process.communicate(task.model_dump_json().encode()))
        response = None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                while not communication.done():
                    if task.task_id in self.cancelled:
                        raise PluginResultError("PLUGIN_CANCELLED")
                    request_path = directory / "request.json"
                    if response is None and request_path.exists():
                        raw = read_message(request_path)
                        if set(raw) != {"task_id", "capability", "prompt_or_instruction", "workspace", "artifact_refs"}:
                            raise PluginResultError("invalid channel request")
                        request = ChannelRequest(**raw)
                        if (request.task_id != task.task_id or
                            request.workspace != task.project.workspace_uri or
                            request.capability != task.execution.master_capability or
                            not isinstance(request.prompt_or_instruction, str) or
                            not isinstance(request.artifact_refs, list) or
                            any(not isinstance(ref, str) for ref in request.artifact_refs)):
                            raise PluginResultError("channel request does not match task")
                        response = await self.execute_channel(request)
                        publish(directory / "response.json", asdict(response))
                    await asyncio.sleep(0.02)
                output, _ = await communication
                if process.returncode != 0 or len(output) > MAX_MESSAGE:
                    raise PluginResultError("PLUGIN_PROCESS_FAILED")
                try:
                    result = PluginResult.model_validate_json(output)
                except ValueError:
                    raise PluginResultError("PLUGIN_RESULT_INVALID") from None
                if result.task_id != task.task_id or result.status not in {"COMPLETED", "FAILED"}:
                    raise PluginResultError("invalid plugin result identity/status")
                if response is None or (result.status == "COMPLETED" and not response.success):
                    raise PluginResultError("plugin completed without successful channel")
                summary = result.execution_summary
                if (summary.api_calls != 0 or summary.api_spend_usd != 0 or
                    summary.subscription_calls != 1 or summary.retries != 0):
                    raise PluginResultError("plugin usage disagrees with transport")
                # The current transport exposes exactly the channel output artifact.
                if (len(result.outputs) != int(response.output_ref is not None) or
                    any(item.uri != response.output_ref for item in result.outputs)):
                    raise PluginResultError("plugin returned an unobserved artifact")
                if result.handoff_uri is not None:
                    raise PluginResultError("handoff is not supported by protocol 1.0")
                return result
        except BaseException as error:
            try:
                await self.cancel_channel(task.task_id)
            finally:
                await terminate_tree(process)
            if isinstance(error, asyncio.CancelledError):
                raise
            raise PluginResultError("PLUGIN_TRANSPORT_FAILED") from None
        finally:
            await asyncio.gather(communication, return_exceptions=True)
            self.active.pop(task.task_id, None)
            # Transport files contain no authoritative state and are not replayed.
            for name in ("context.json", "request.json", "response.json", "channel.claim"):
                (directory / name).unlink(missing_ok=True)

    async def pause(self, task_id: str) -> None:
        raise PluginUnavailableError("safe plugin checkpoint is not available in M4")

    async def resume(self, task_id: str) -> PluginResult:
        raise PluginUnavailableError("plugin resume is not available in M4")

    async def cancel(self, task_id: str) -> None:
        if task_id not in self.active:
            return
        self.cancelled.add(task_id)
        process = self.active[task_id]
        try:
            await self.cancel_channel(task_id)
        finally:
            await terminate_tree(process)
