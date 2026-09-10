"""Codex subscription channel adapter."""

import json
import os
from pathlib import Path

from .base import ChannelRequest
from ._cli_health import CliSubscriptionAdapter, CommandResult


_TOKEN_KEYS = frozenset(
    {"input_tokens", "cached_input_tokens", "output_tokens", "total_tokens"}
)


class CodexAdapter(CliSubscriptionAdapter):
    surface = "codex"
    status_command = ("codex", "login", "status")

    def __init__(
        self,
        *,
        channel_id: str = "codex-subscription",
        model: str | None = None,
        sandbox: str = "read-only",
        isolated_tools: bool = False,
        **kwargs,
    ) -> None:
        if sandbox not in {"read-only", "workspace-write"}:
            raise ValueError("Codex sandbox must be read-only or workspace-write")
        self.sandbox = sandbox
        self.isolated_tools = isolated_tools
        super().__init__(channel_id=channel_id, model=model, **kwargs)

    def _build_execution_command(
        self, request: ChannelRequest, output_path: Path
    ) -> tuple[str, ...]:
        command = [
            "codex",
            "exec",
            "--ephemeral",
            "--color",
            "never",
            "--json",
            "--sandbox",
            self.sandbox,
            "--cd",
            str(Path(request.workspace).resolve()),
            "--output-last-message",
            str(output_path),
        ]
        if self.model:
            command.extend(("--model", self.model))
        if self.isolated_tools:
            command.extend(("--ignore-user-config", "--disable", "apps", "--skip-git-repo-check"))
            if os.name == "nt":
                # Preserve the host's configured stronger Windows sandbox even
                # when user MCP/provider configuration is excluded.
                command.extend(("-c", 'windows.sandbox="elevated"'))
        command.append("-")
        return tuple(command)

    def _complete_output(
        self,
        result: CommandResult,
        output_path: Path,
    ) -> dict:
        super()._complete_output(result, output_path)
        usage: dict[str, int] = {}
        for line in result.stdout.splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            candidate = payload.get("usage")
            if not isinstance(candidate, dict):
                continue
            for key in _TOKEN_KEYS:
                value = candidate.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    usage[key] = value
        return usage
