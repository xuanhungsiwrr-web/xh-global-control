from hashlib import sha256

import pytest

from xh_control.channels import ChannelRequest, ChannelResponse, ExecutionChannelAdapter
from xh_control.config import load_config
from xh_control.core import (
    ArtifactService,
    ChannelExecutionService,
    EventService,
    TaskService,
)
from xh_control.exceptions import BudgetStateError, InvalidGenerationError
from xh_control.learning import OperationalMetricsService
from xh_control.models import TaskEnvelope, TaskStatus
from xh_control.state import (
    ArtifactRepository,
    CostRepository,
    EventRepository,
    GlobalLearningRepository,
    TaskRepository,
    initialize_database,
)


def run_immediate(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("I/O-free channel flow unexpectedly suspended")


class FakeChannelAdapter(ExecutionChannelAdapter):
    def __init__(self, response):
        self.response = response
        self.requests = []

    async def healthcheck(self) -> dict:
        return {"health": "AVAILABLE"}

    async def execute(self, request: ChannelRequest) -> ChannelResponse:
        self.requests.append(request)
        return self.response

    async def cancel(self, task_id: str) -> None:
        return None


def envelope(task_id, workspace):
    return TaskEnvelope(
        task_id=task_id,
        created_at="2026-09-09T00:00:00Z",
        task_type="generic",
        plugin="generic-plugin",
        project={"project_id": "P", "workspace_uri": str(workspace)},
        execution={},
        permissions={"level": "SAFE_EDIT"},
        budget={"api_soft_usd": 0, "api_hard_usd": 0},
        user_request="opaque",
    )


def running_execution(config_root, tmp_path, task_id="T-M4-GENERIC"):
    config = load_config(config_root)
    database = initialize_database(config)
    tasks = TaskService(TaskRepository(database))
    tasks.create_task(envelope(task_id, tmp_path))
    attempt = tasks.create_attempt(task_id, "pc-main", "codex-subscription")
    tasks.transition_task(task_id, TaskStatus.QUEUED)
    tasks.transition_task(task_id, TaskStatus.ASSIGNED)
    tasks.transition_task(task_id, TaskStatus.RUNNING)
    tasks.transition_attempt(
        task_id, attempt.attempt_id, attempt.generation, TaskStatus.RUNNING
    )
    return config, database, tasks, attempt


def test_fenced_subscription_execution_persists_artifact_cost_metrics_and_audit(
    config_root, tmp_path
):
    config, database, tasks, attempt = running_execution(config_root, tmp_path)
    output = tmp_path / "channel-output.txt"
    output.write_text("real-shaped output", encoding="utf-8")
    response = ChannelResponse(
        success=True,
        output_ref=output.resolve().as_uri(),
        usage={"input_tokens": 9, "output_tokens": 4},
        latency_seconds=0.75,
    )
    adapter = FakeChannelAdapter(response)
    events = EventService(EventRepository(database))
    artifacts = ArtifactService(ArtifactRepository(database))
    costs = CostRepository(database)
    learning = GlobalLearningRepository(database)
    service = ChannelExecutionService(
        tasks,
        events,
        artifacts,
        OperationalMetricsService(
            costs,
            learning,
            learning_event_id_factory=lambda: "LE-CHANNEL",
        ),
        config.channels,
        lambda task, channel: adapter,
    )
    request = ChannelRequest(
        task_id="T-M4-GENERIC",
        capability="MASTER",
        prompt_or_instruction="opaque",
        workspace=str(tmp_path),
    )

    returned = run_immediate(
        service.execute(
            task_id="T-M4-GENERIC",
            attempt_id=attempt.attempt_id,
            generation=attempt.generation,
            request=request,
        )
    )

    assert returned is response
    assert adapter.requests == [request]
    artifact = artifacts.list_for_task("T-M4-GENERIC")[0]
    assert artifact.attempt_id == attempt.attempt_id
    assert artifact.uri == output.resolve().as_uri()
    assert artifact.size_bytes == len(b"real-shaped output")
    assert artifact.sha256 == sha256(b"real-shaped output").hexdigest()
    assert costs.list_for_task("T-M4-GENERIC")[0].estimated_usd == 0
    assert learning.list_for_task("T-M4-GENERIC")[0].estimated_context_tokens == 9
    event_types = [item.event_type for item in events.list_for_task("T-M4-GENERIC")]
    assert "ARTIFACT_REGISTERED" in event_types
    assert "COST_RECORDED" in event_types
    assert "OPERATIONAL_METRICS_RECORDED" in event_types
    assert "CHANNEL_EXECUTION_FINISHED" in event_types


def test_stale_attempt_is_rejected_before_adapter_invocation(config_root, tmp_path):
    config, database, tasks, attempt = running_execution(config_root, tmp_path)
    adapter = FakeChannelAdapter(
        ChannelResponse(True, "file:///unused", {}, 0.1)
    )
    service = ChannelExecutionService(
        tasks,
        EventService(EventRepository(database)),
        ArtifactService(ArtifactRepository(database)),
        OperationalMetricsService(
            CostRepository(database), GlobalLearningRepository(database)
        ),
        config.channels,
        lambda task, channel: adapter,
    )

    with pytest.raises(InvalidGenerationError):
        run_immediate(
            service.execute(
                task_id="T-M4-GENERIC",
                attempt_id=attempt.attempt_id,
                generation=attempt.generation + 1,
                request=ChannelRequest(
                    task_id="T-M4-GENERIC",
                    capability="MASTER",
                    prompt_or_instruction="opaque",
                    workspace=str(tmp_path),
                ),
            )
        )
    assert adapter.requests == []


def test_paid_channel_cannot_bypass_budget_engine(config_root, tmp_path):
    config, database, tasks, attempt = running_execution(config_root, tmp_path)
    paid = config.channels["codex-subscription"].model_copy(
        update={"channel_id": "paid", "channel_class": "cheap_api", "billing_mode": "api"}
    )
    tasks.repository.database_path = database
    with tasks.repository.connection() as connection, connection:
        connection.execute(
            "UPDATE execution_attempts SET channel_id = 'paid' WHERE attempt_id = ?",
            (attempt.attempt_id,),
        )
        connection.execute(
            "UPDATE tasks SET resolved_channel_id = 'paid' WHERE task_id = 'T-M4-GENERIC'"
        )
    adapter = FakeChannelAdapter(ChannelResponse(True, "file:///unused", {}, 0.1))
    service = ChannelExecutionService(
        tasks,
        EventService(EventRepository(database)),
        ArtifactService(ArtifactRepository(database)),
        OperationalMetricsService(
            CostRepository(database), GlobalLearningRepository(database)
        ),
        {"paid": paid},
        lambda task, channel: adapter,
    )

    with pytest.raises(BudgetStateError, match="BudgetEngine"):
        run_immediate(
            service.execute(
                task_id="T-M4-GENERIC",
                attempt_id=attempt.attempt_id,
                generation=attempt.generation,
                request=ChannelRequest(
                    task_id="T-M4-GENERIC",
                    capability="MASTER",
                    prompt_or_instruction="opaque",
                    workspace=str(tmp_path),
                ),
            )
        )
    assert adapter.requests == []
