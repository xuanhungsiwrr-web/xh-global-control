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
from xh_control.exceptions import PluginPausedSignal, PluginResultError, PluginUnavailableError
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
        self._directories: dict[str, Path] = {}
        self._pause_outcomes: dict[str, asyncio.Future[bool]] = {}
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
            protocol_version = health.get("protocol_version") if isinstance(health, dict) else None
            return (
                process.returncode == 0
                and isinstance(protocol_version, str)
                and protocol_version.startswith("1.")
                and health.get("healthy") is True
            )
        except (ValueError, TimeoutError):
            await terminate_tree(process)
            return False
        except asyncio.CancelledError:
            await terminate_tree(process)
            raise

    async def execute(self, task: TaskEnvelope) -> PluginResult:
        return await self._execute(task)

    async def _execute(self, task: TaskEnvelope, context_overrides: dict | None = None) -> PluginResult:
        if task.task_id in self.active:
            raise PluginResultError("task already executing")
        if task.task_id != self.context["task_id"]:
            raise PluginResultError("task does not match bound context")
        directory = self.runtime_root / uuid4().hex
        directory.mkdir(parents=True)
        context = self.context | (context_overrides or {}) | {
            "protocol_version": "1.1",
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
        self._directories[task.task_id] = directory
        pause_outcome = asyncio.get_running_loop().create_future()
        self._pause_outcomes[task.task_id] = pause_outcome
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
                    raw_output = json.loads(output)
                except ValueError:
                    raise PluginResultError("PLUGIN_RESULT_INVALID") from None
                if (
                    isinstance(raw_output, dict)
                    and set(raw_output) == {"protocol_version", "task_id", "handoff_uri"}
                    and raw_output.get("protocol_version") == "1.1"
                    and raw_output.get("task_id") == task.task_id
                ):
                    if await pause_outcome:
                        raise PluginPausedSignal("plugin paused with durable handoff")
                    raise PluginResultError("plugin pause persistence failed")
                try:
                    result = PluginResult.model_validate(raw_output)
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
        except PluginPausedSignal:
            raise
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
            self._directories.pop(task.task_id, None)
            self._pause_outcomes.pop(task.task_id, None)
            # Transport files contain no authoritative state and are not replayed.
            for name in ("context.json", "request.json", "response.json", "channel.claim",
                         "pause.request.json", "pause.response.json"):
                (directory / name).unlink(missing_ok=True)

    async def pause(self, task_id: str) -> str:
        """Ask the plugin process for an opaque, durable handoff URI.

        The response contains only the URI. Global never opens or interprets
        the referenced handoff document.
        """
        directory = self._directories.get(task_id)
        if directory is None:
            raise PluginUnavailableError("task is not actively executing")
        process = self.active[task_id]
        publish(directory / "pause.request.json", {
            "protocol_version": "1.1", "task_id": task_id,
        })
        response_path = directory / "pause.response.json"
        deadline = asyncio.get_running_loop().time() + min(self.timeout_seconds, 30)
        while asyncio.get_running_loop().time() < deadline:
            if response_path.exists():
                try:
                    response = read_message(response_path)
                except (OSError, ValueError) as exc:
                    raise PluginResultError("invalid plugin pause response") from exc
                if set(response) != {"protocol_version", "task_id", "handoff_uri"}:
                    raise PluginResultError("invalid plugin pause response")
                if response["protocol_version"] != "1.1" or response["task_id"] != task_id:
                    raise PluginResultError("plugin pause response does not match task")
                handoff_uri = response["handoff_uri"]
                if not isinstance(handoff_uri, str) or not handoff_uri.strip():
                    raise PluginResultError("plugin pause response has no handoff URI")
                try:
                    await asyncio.wait_for(process.wait(), min(self.timeout_seconds, 30))
                except TimeoutError as exc:
                    raise PluginUnavailableError("plugin did not stop after safe handoff") from exc
                return handoff_uri
            await asyncio.sleep(0.02)
        raise PluginUnavailableError("plugin did not provide a safe handoff URI")

    def complete_pause(self, task_id: str, persisted: bool) -> None:
        outcome = self._pause_outcomes.get(task_id)
        if outcome is not None and not outcome.done():
            outcome.set_result(persisted)

    async def resume(self, task: TaskEnvelope, handoff_uri: str) -> PluginResult:
        if not isinstance(handoff_uri, str) or not handoff_uri.strip():
            raise PluginResultError("resume requires a non-empty handoff URI")
        return await self._execute(task, {"resume_handoff_uri": handoff_uri})

    async def cancel(self, task_id: str) -> None:
        if task_id not in self.active:
            return
        self.cancelled.add(task_id)
        process = self.active[task_id]
        try:
            await self.cancel_channel(task_id)
        finally:
            await terminate_tree(process)
