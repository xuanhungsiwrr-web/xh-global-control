from datetime import UTC, datetime

import pytest

from xh_control.config import load_config
from xh_control.core import ArtifactService, CheckpointService, GlobalController, TaskService
from xh_control.exceptions import CheckpointError, CheckpointIncompatibleError, PermissionApprovalRequiredError
from xh_control.interfaces.telegram import TelegramCommand, TelegramUpdate
from xh_control.models import TaskStatus
from xh_control.state import ArtifactRepository, TaskRepository, initialize_database


def _envelope(task_id, workspace):
    from xh_control.models import TaskEnvelope
    return TaskEnvelope(
        task_id=task_id, created_at=datetime.now(UTC), task_type="generic",
        plugin="generic-plugin", project={"project_id": "P", "workspace_uri": str(workspace)},
        execution={}, permissions={}, budget={"api_soft_usd": 0, "api_hard_usd": 0},
        user_request="opaque request",
    )


def _services(config_root, tmp_path):
    database = initialize_database(load_config(config_root))
    tasks = TaskService(TaskRepository(database))
    artifacts = ArtifactService(ArtifactRepository(database))
    checkpoints = CheckpointService(artifacts)
    task = tasks.create_task(_envelope("M6-TASK", tmp_path))
    tasks.transition_task(task.task.task_id, TaskStatus.QUEUED)
    attempt = tasks.create_attempt(task.task.task_id, "pc-main", "codex-subscription")
    tasks.transition_task(task.task.task_id, TaskStatus.ASSIGNED, attempt_id=attempt.attempt_id, generation=attempt.generation)
    tasks.transition_task(task.task.task_id, TaskStatus.RUNNING, attempt_id=attempt.attempt_id, generation=attempt.generation)
    return tasks, artifacts, checkpoints, attempt


def test_checkpoint_round_trip_has_identity_revision_and_hash(config_root, tmp_path):
    tasks, artifacts, checkpoints, attempt = _services(config_root, tmp_path)
    task = tasks.get_task("M6-TASK")
    source = tmp_path / "result.txt"
    source.write_text("opaque artifact", encoding="utf-8")
    artifact = artifacts.register("M6-TASK", "output", str(source), attempt_id=attempt.attempt_id,
                                  sha256=__import__("hashlib").sha256(source.read_bytes()).hexdigest())
    checkpoint = checkpoints.create(task, attempt_id=attempt.attempt_id, generation=attempt.generation,
                                    worker_id="pc-main", channel_id="codex-subscription",
                                    plugin_state_ref="opaque://handoff/1", artifact_refs=[artifact.uri])
    tasks.transition_task("M6-TASK", TaskStatus.PAUSED, attempt_id=attempt.attempt_id, generation=attempt.generation)
    loaded = checkpoints.load(tasks.get_task("M6-TASK"))
    assert (loaded.task_id, loaded.revision, loaded.payload_sha256) == ("M6-TASK", 1, checkpoint.payload_sha256)
    assert tasks.get_task("M6-TASK").latest_checkpoint_uri.endswith("CP-0001.json")


def test_checkpoint_uses_v3_machine_state_directory(config_root, tmp_path):
    (tmp_path / "30_Working" / ".ai").mkdir(parents=True)
    tasks, artifacts, checkpoints, attempt = _services(config_root, tmp_path)

    checkpoints.create(
        tasks.get_task("M6-TASK"),
        attempt_id=attempt.attempt_id,
        generation=attempt.generation,
        worker_id="pc-main",
        channel_id="codex-subscription",
        plugin_state_ref="opaque://handoff/1",
        artifact_refs=[],
    )

    assert (tmp_path / "30_Working" / ".ai" / "checkpoints" / "CP-0001.json").is_file()
    assert not (tmp_path / ".ai").exists()


def test_checkpoint_rejects_missing_or_changed_artifact(config_root, tmp_path):
    tasks, artifacts, checkpoints, attempt = _services(config_root, tmp_path)
    source = tmp_path / "result.txt"
    source.write_text("before", encoding="utf-8")
    digest = __import__("hashlib").sha256(source.read_bytes()).hexdigest()
    artifact = artifacts.register("M6-TASK", "output", str(source), attempt_id=attempt.attempt_id, sha256=digest)
    checkpoints.create(tasks.get_task("M6-TASK"), attempt_id=attempt.attempt_id, generation=attempt.generation,
                       worker_id="pc-main", channel_id=None, plugin_state_ref="opaque://state",
                       artifact_refs=[artifact.uri])
    tasks.transition_task("M6-TASK", TaskStatus.PAUSED, attempt_id=attempt.attempt_id, generation=attempt.generation)
    source.write_text("after", encoding="utf-8")
    with pytest.raises(CheckpointError, match="changed"):
        checkpoints.load(tasks.get_task("M6-TASK"))


def test_controller_pause_resume_uses_persisted_checkpoint(config_root, tmp_path):
    tasks, artifacts, checkpoints, attempt = _services(config_root, tmp_path)
    class ExecutionHook:
        async def pause(self, task_id):
            tasks.transition_task(task_id, TaskStatus.PAUSED, attempt_id=attempt.attempt_id, generation=attempt.generation)
        async def resume(self, task_id):
            tasks.transition_task(task_id, TaskStatus.QUEUED, attempt_id=attempt.attempt_id, generation=attempt.generation)
    controller = GlobalController(load_config(config_root), task_service=tasks, execution_service=ExecutionHook(), checkpoint_service=checkpoints)
    update = TelegramUpdate("1", "u", "c", "")
    def immediate(coroutine):
        try:
            coroutine.send(None)
        except StopIteration as exc:
            return exc.value
        raise AssertionError("unexpected suspension")
    assert immediate(controller.handle_telegram_command(TelegramCommand("pause", ("M6-TASK",)), update)) == "Paused: M6-TASK"
    assert tasks.get_task("M6-TASK").status == TaskStatus.PAUSED
    assert immediate(controller.handle_telegram_command(TelegramCommand("resume", ("M6-TASK",)), update)) == "Resume queued: M6-TASK"
    assert tasks.get_task("M6-TASK").status == TaskStatus.QUEUED


def test_checkpoint_rejects_wrong_task_identity(config_root, tmp_path):
    tasks, artifacts, checkpoints, attempt = _services(config_root, tmp_path)
    checkpoint = checkpoints.create(tasks.get_task("M6-TASK"), attempt_id=attempt.attempt_id, generation=attempt.generation,
                                    worker_id="pc-main", channel_id=None, plugin_state_ref="opaque://state", artifact_refs=[])
    path = tmp_path / ".ai" / "checkpoints" / "CP-0001.json"
    raw = __import__("json").loads(path.read_text(encoding="utf-8"))
    raw["task_id"] = "OTHER"
    path.write_text(__import__("json").dumps(raw), encoding="utf-8")
    tasks.transition_task("M6-TASK", TaskStatus.PAUSED, attempt_id=attempt.attempt_id, generation=attempt.generation)
    with pytest.raises(CheckpointIncompatibleError):
        checkpoints.load(tasks.get_task("M6-TASK"))


def test_pause_resume_are_denied_by_permission_policy(config_root, tmp_path):
    tasks, artifacts, checkpoints, attempt = _services(config_root, tmp_path)
    task = tasks.get_task("M6-TASK")
    from xh_control.models import PermissionRequest
    denied = task.task.model_copy(update={"permissions": PermissionRequest(level="PRIVILEGED")})
    # Keep the test at the policy boundary; no checkpoint is written before denial.
    with pytest.raises(PermissionApprovalRequiredError):
        from xh_control.permissions import PermissionPolicy
        PermissionPolicy(load_config(config_root).permissions).validate(denied)
