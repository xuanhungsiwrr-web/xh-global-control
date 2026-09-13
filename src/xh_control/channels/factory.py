"""Create task-scoped channel adapters from resolved channel configuration."""

from pathlib import Path

from xh_control.config import Configuration
from xh_control.exceptions import ChannelError
from xh_control.models import ExecutionChannel, TaskEnvelope
from xh_control.permissions import PermissionPolicy

from .base import ExecutionChannelAdapter
from .claude_code import ClaudeCodeAdapter
from .codex import CodexAdapter


class ChannelAdapterFactory:
    """Bind permission policy without changing the channel request contract."""

    def __init__(
        self,
        configuration: Configuration,
        *,
        output_root: Path | str | None = None,
    ) -> None:
        self.configuration = configuration
        self.permission_policy = PermissionPolicy(configuration.permissions)
        configured_root = configuration.artifact_path
        self.output_root = Path(output_root or configured_root).resolve()

    def create(
        self,
        task: TaskEnvelope,
        channel: ExecutionChannel,
    ) -> ExecutionChannelAdapter:
        if channel.surface == "codex":
            return CodexAdapter(
                channel_id=channel.channel_id,
                model=channel.model,
                sandbox=self.permission_policy.codex_sandbox(task),
                output_root=self.output_root,
            )
        if channel.surface == "claude_code":
            manifest = self.configuration.plugins.get(task.plugin)
            read_dirs = tuple(
                Path(value).resolve()
                for value in sorted(manifest.channel_read_roots if manifest else ())
                if Path(value).is_absolute() and Path(value).is_dir()
            )
            return ClaudeCodeAdapter(
                channel_id=channel.channel_id,
                model=channel.model,
                permission_mode=self.permission_policy.claude_permission_mode(task),
                additional_read_dirs=read_dirs,
                allowed_tools=tuple(sorted(manifest.channel_allowed_tools if manifest else ())),
                output_root=self.output_root,
            )
        raise ChannelError(f"Unsupported M4 execution surface: {channel.surface}")
