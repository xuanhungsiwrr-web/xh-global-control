import json

import pytest

from xh_control.config import load_config
from xh_control.core import (
    ArtifactService,
    EventService,
    PluginExecutionService,
    TaskService,
)
from xh_control.exceptions import PluginResultError, PluginTaskTypeError
from xh_control.models import PluginManifest, PluginResult, TaskEnvelope, TaskStatus
from xh_control.plugins import DomainPluginAdapter, PluginRegistry
from xh_control.state import (
    ArtifactRepository,
    EventRepository,
    TaskRepository,
    initialize_database,
)


def run_immediate(coroutine):
    """Drive the I/O-free mock flow without creating a Windows socket loop."""
    try:
        coroutine.send(None)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("mock coroutine unexpectedly suspended")


class MockDomainAdapter(DomainPluginAdapter):
    def __init__(self, result):
        self.result = result
        self.received = []

    async def healthcheck(self) -> bool:
        return True

    async def execute(self, task: TaskEnvelope) -> PluginResult:
        self.received.append(task)
        return self.result

    async def pause(self, task_id: str) -> str:
        return "opaque://handoff"

    async def resume(self, task: TaskEnvelope, handoff_uri: str) -> PluginResult:
        return self.result

    async def cancel(self, task_id: str) -> None:
        return None


def envelope(task_id, plugin="xh-tuvan", task_type="generate_report"):
    return TaskEnvelope(
        task_id=task_id,
        created_at="2026-09-08T00:00:00Z",
        task_type=task_type,
        plugin=plugin,
        report_type="opaque-report-type" if plugin == "xh-tuvan" else None,
        project={"project_id": "P-1", "workspace_uri": "drive://project"},
        execution={},
        permissions={},
        budget={"api_soft_usd": 1, "api_hard_usd": 3},
        user_request="Opaque domain request that Global must not parse",
    )


def manifest(plugin_id="xh-tuvan", task_type="generate_report"):
    return PluginManifest(
        plugin_id=plugin_id,
        version="1.test",
        interface_version="1.0",
        domain="opaque-domain",
        entrypoint_type="mock",
        entrypoint="tests.MockDomainAdapter",
        accepted_task_types={task_type},
    )


def valid_result(task_id):
    return {
        "schema_version": "1.0",
        "task_id": task_id,
        "status": "COMPLETED",
        "outputs": [
            {
                "artifact_type": "opaque-output",
                "uri": "drive://project/output.bin",
                "sha256": "abc123",
            }
        ],
        "execution_summary": {
            "elapsed_seconds": 1.5,
            "subscription_calls": 1,
        },
        "global_learning": {
            "model_performance": [{"success": True, "score": 0.9}],
            "routing": [{"selected": "mock"}],
        },
        "domain_learning_stored_by_plugin": True,
        "domain_learning_candidate_count": 2,
    }


@pytest.fixture
def services(config_root):
    path = initialize_database(load_config(config_root))
    tasks = TaskService(TaskRepository(path))
    events = EventService(EventRepository(path))
    artifacts = ArtifactService(ArtifactRepository(path))
    registry = PluginRegistry()
    runner = PluginExecutionService(tasks, events, artifacts, registry)
    return tasks, events, artifacts, registry, runner


def test_mock_xh_tuvan_completes_and_persists_contract_state_and_audit(services):
    tasks, events, artifacts, registry, runner = services
    adapter = MockDomainAdapter(valid_result("T-M2-XH"))
    registry.register(manifest(), adapter)
    tasks.create_task(envelope("T-M2-XH"))

    result = run_immediate(runner.execute("T-M2-XH"))

    assert result.status == "COMPLETED"
    assert tasks.get_task("T-M2-XH").status == TaskStatus.COMPLETED
    assert adapter.received == [envelope("T-M2-XH")]
    assert [(item.artifact_type, item.uri) for item in artifacts.list_for_task("T-M2-XH")] == [
        ("opaque-output", "drive://project/output.bin")
    ]
    event_types = [event.event_type for event in events.list_for_task("T-M2-XH")]
    assert event_types == [
        "TASK_CREATED",
        "TASK_STATUS_CHANGED",
        "TASK_STATUS_CHANGED",
        "TASK_STATUS_CHANGED",
        "PLUGIN_EXECUTION_STARTED",
        "ARTIFACT_REGISTERED",
        "PLUGIN_RESULT_ACCEPTED",
        "TASK_STATUS_CHANGED",
    ]


@pytest.mark.parametrize(
    "bad_result",
    [
        {
            "task_id": "T-M2-BAD",
            "status": "COMPLETED",
            "global_learning": {},
        },
        valid_result("A-DIFFERENT-TASK"),
        valid_result("T-M2-BAD") | {"status": "RUNNING"},
        valid_result("T-M2-BAD") | {"schema_version": "9.0"},
    ],
)
def test_bad_plugin_result_is_rejected_without_false_completion(services, bad_result):
    tasks, events, _, registry, runner = services
    registry.register(manifest(), MockDomainAdapter(bad_result))
    tasks.create_task(envelope("T-M2-BAD"))

    with pytest.raises(PluginResultError, match="invalid contract"):
        run_immediate(runner.execute("T-M2-BAD"))

    assert tasks.get_task("T-M2-BAD").status == TaskStatus.FAILED
    assert "PLUGIN_RESULT_ACCEPTED" not in [
        event.event_type for event in events.list_for_task("T-M2-BAD")
    ]


def test_domain_learning_rejected_from_global(services):
    tasks, events, _, registry, runner = services
    bad_result = valid_result("T-M2-DOMAIN")
    bad_result["global_learning"] = {
        "model_performance": [
            {"metrics": {"legal_rule": "sensitive domain content"}}
        ]
    }
    registry.register(manifest(), MockDomainAdapter(bad_result))
    tasks.create_task(envelope("T-M2-DOMAIN"))

    with pytest.raises(PluginResultError, match="invalid contract"):
        run_immediate(runner.execute("T-M2-DOMAIN"))

    assert tasks.get_task("T-M2-DOMAIN").status == TaskStatus.FAILED
    audit = json.dumps(
        [event.model_dump(mode="json") for event in events.list_for_task("T-M2-DOMAIN")]
    )
    assert "legal_rule" not in audit
    assert "sensitive domain content" not in audit
    assert "PLUGIN_RESULT_ACCEPTED" not in audit


def test_unaccepted_task_type_never_invokes_plugin_or_completes_task(services):
    tasks, _, _, registry, runner = services
    adapter = MockDomainAdapter(valid_result("T-M2-TYPE"))
    registry.register(manifest(), adapter)
    tasks.create_task(envelope("T-M2-TYPE", task_type="unsupported"))

    with pytest.raises(PluginTaskTypeError):
        run_immediate(runner.execute("T-M2-TYPE"))

    assert tasks.get_task("T-M2-TYPE").status == TaskStatus.CREATED
    assert adapter.received == []


def test_generic_plugin_replaces_xh_tuvan_without_global_workflow_changes(services):
    tasks, events, artifacts, registry, runner = services
    adapter = MockDomainAdapter(valid_result("T-M2-GENERIC"))
    registry.register(manifest("generic-plugin", "generic"), adapter)
    tasks.create_task(envelope("T-M2-GENERIC", "generic-plugin", "generic"))

    run_immediate(runner.execute("T-M2-GENERIC"))

    assert tasks.get_task("T-M2-GENERIC").status == TaskStatus.COMPLETED
    assert len(artifacts.list_for_task("T-M2-GENERIC")) == 1
    accepted = [
        event for event in events.list_for_task("T-M2-GENERIC")
        if event.event_type == "PLUGIN_RESULT_ACCEPTED"
    ]
    assert accepted[0].payload["plugin_id"] == "generic-plugin"
