"""Claude Code subscription channel health adapter."""

import json
from pathlib import Path

from xh_control.models import ChannelHealth

from .base import ChannelRequest
from ._cli_health import CliSubscriptionAdapter, CommandResult


class ClaudeCodeAdapter(CliSubscriptionAdapter):
    surface = "claude_code"
    status_command = ("claude", "auth", "status", "--json")

    def __init__(
        self,
        *,
        channel_id: str = "claude-code-subscription",
        model: str | None = None,
        permission_mode: str = "plan",
        **kwargs,
    ) -> None:
        if permission_mode not in {"plan", "default"}:
            raise ValueError("Claude permission mode must be plan or default")
        self.permission_mode = permission_mode
        super().__init__(channel_id=channel_id, model=model, **kwargs)

    def _interpret_status(
        self, result: CommandResult
    ) -> tuple[ChannelHealth, str]:
        if result.returncode != 0:
            return ChannelHealth.UNAVAILABLE, "CLI_AUTH_UNAVAILABLE"
        try:
            payload = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            return ChannelHealth.UNKNOWN, "CLI_STATUS_UNRECOGNIZED"
        logged_in = payload.get("loggedIn") if isinstance(payload, dict) else None
        if logged_in is True:
            return ChannelHealth.AVAILABLE, "CLI_AUTHENTICATED"
        if logged_in is False:
            return ChannelHealth.UNAVAILABLE, "CLI_AUTH_UNAVAILABLE"
        return ChannelHealth.UNKNOWN, "CLI_STATUS_UNRECOGNIZED"

    def _build_execution_command(
        self, request: ChannelRequest, output_path: Path
    ) -> tuple[str, ...]:
        command = [
            "claude",
            "--print",
            "--output-format",
            "json",
            "--permission-mode",
            self.permission_mode,
        ]
        if self.model:
            command.extend(("--model", self.model))
        return tuple(command)

    def _complete_output(
        self,
        result: CommandResult,
        output_path: Path,
    ) -> dict:
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise ValueError("Claude did not return JSON output") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("result"), str):
            raise ValueError("Claude JSON output has no result text")
        output_path.write_text(payload["result"], encoding="utf-8")
        reported = payload.get("usage")
        if not isinstance(reported, dict):
            return {}
        usage: dict[str, int] = {}
        for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"):
            value = reported.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                usage[key] = value
        return usage
