import pytest

from xh_control.config import load_config
from xh_control.channels import ChannelAdapterFactory, CodexAdapter
from xh_control.exceptions import PermissionApprovalRequiredError
from xh_control.models import PermissionLevel, TaskEnvelope
from xh_control.permissions import PermissionPolicy


def task(level):
    return TaskEnvelope(
        task_id=f"T-{level}",
        created_at="2026-09-08T00:00:00Z",
        task_type="generic",
        plugin="generic-plugin",
        project={"project_id": "P", "workspace_uri": "D:/trial"},
        execution={},
        permissions={"level": level},
        budget={"api_soft_usd": 0, "api_hard_usd": 0},
        user_request="opaque",
    )


def test_safe_edit_keeps_model_project_workspace_read_only():
    policy = PermissionPolicy(load_config().permissions)

    assert policy.codex_sandbox(task(PermissionLevel.SAFE_EDIT)) == "read-only"
    assert policy.claude_permission_mode(task(PermissionLevel.SAFE_EDIT)) == "plan"

    config = load_config()
    adapter = ChannelAdapterFactory(config).create(
        task(PermissionLevel.SAFE_EDIT), config.channels["codex-subscription"]
    )
    assert isinstance(adapter, CodexAdapter)
    assert adapter.sandbox == "read-only"


def test_project_write_must_be_explicit_and_never_maps_to_dangerous_bypass():
    policy = PermissionPolicy(load_config().permissions)

    assert policy.codex_sandbox(task(PermissionLevel.PROJECT_WRITE)) == "workspace-write"
    with pytest.raises(PermissionApprovalRequiredError, match="tool policy"):
        policy.claude_permission_mode(task(PermissionLevel.PROJECT_WRITE))


@pytest.mark.parametrize("level", [PermissionLevel.SYSTEM_WRITE, PermissionLevel.PRIVILEGED])
def test_elevated_permissions_require_approval(level):
    policy = PermissionPolicy(load_config().permissions)

    with pytest.raises(PermissionApprovalRequiredError):
        policy.codex_sandbox(task(level))
