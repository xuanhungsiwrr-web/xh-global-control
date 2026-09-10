"""Map granted task permissions to non-interactive channel sandboxes."""

from xh_control.config import PermissionFlags, PermissionsConfig
from xh_control.exceptions import PermissionApprovalRequiredError, PermissionPolicyError
from xh_control.models import PermissionLevel, TaskEnvelope


class PermissionPolicy:
    def __init__(self, configuration: PermissionsConfig) -> None:
        self.configuration = configuration

    def validate(self, task: TaskEnvelope) -> PermissionFlags:
        level = task.permissions.level
        configured = self.configuration.levels[level]
        if level == PermissionLevel.PRIVILEGED:
            raise PermissionApprovalRequiredError(
                "PRIVILEGED execution requires an explicit approval"
            )
        if not isinstance(configured, PermissionFlags):
            raise PermissionPolicyError(f"Invalid permission policy for {level.value}")
        if configured.approval_required:
            raise PermissionApprovalRequiredError(
                f"{level.value} execution requires an explicit approval"
            )
        return configured

    def codex_sandbox(self, task: TaskEnvelope) -> str:
        flags = self.validate(task)
        # SAFE_EDIT can write only to Global's separate temp/artifact root, not
        # the project workspace, so the model-facing project sandbox stays read-only.
        return "workspace-write" if flags.write_project else "read-only"

    def claude_permission_mode(self, task: TaskEnvelope) -> str:
        flags = self.validate(task)
        if flags.write_project:
            # Non-interactive edit permissions need an approved, explicit tool
            # policy/bridge. Do not silently use --dangerously-skip-permissions.
            raise PermissionApprovalRequiredError(
                "Claude project writes require an explicit non-interactive tool policy"
            )
        return "plan"
