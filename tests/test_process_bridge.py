"""Actual generic fixture processes with fake channels; no installed plugin needed."""

import asyncio
import json
from pathlib import Path
import sys
import socket

import pytest

from xh_control.channels import ChannelResponse
from xh_control.config import load_config
from xh_control.core.process_execution_service import ProcessExecutionService
from xh_control.exceptions import PluginPausedSignal, PluginResultError, PermissionApprovalRequiredError
from xh_control.models import TaskEnvelope, TaskStatus
from xh_control.plugins.process_adapter import ProcessPluginAdapter
from xh_control.state import CostRepository

_connect = socket.socket.connect
_socketpair = socket.socketpair


@pytest.fixture(autouse=True)
def event_loop_socketpair(no_network, monkeypatch):
    # Windows implements asyncio's self-pipe with loopback socketpair. Only
    # unblock connect while stdlib creates that pair, never for task/network I/O.
    def pair(*args, **kwargs):
        with monkeypatch.context() as scoped:
            scoped.setattr(socket.socket, "connect", _connect)
            return _socketpair(*args, **kwargs)
    monkeypatch.setattr(socket, "socketpair", pair)


def envelope(workspace, **patch):
    data = dict(task_id="T-BRIDGE", created_at="2026-09-09T00:00:00Z",
                plugin="xh-tuvan", task_type="analyze_project",
                project={"project_id": "TEST", "workspace_uri": str(workspace)},
                execution={}, permissions={}, budget={"api_soft_usd": 0, "api_hard_usd": 0},
                user_request="opaque test request")
    return TaskEnvelope(**(data | patch))


class FakeChannel:
    def __init__(self, root, payload=None, success=True):
        self.root, self.success = root, success
        self.payload = payload or {"outcome": "completed", "deliverable": "Test-only analysis",
                                   "evidence": ["fixture"], "blockers": []}
        self.calls = []
        self.cancelled = []

    async def healthcheck(self):
        return {"health": "AVAILABLE"}

    async def execute(self, request):
        self.calls.append(request)
        output = self.root / "answer.json"
        output.write_text(json.dumps(self.payload), encoding="utf-8")
        return ChannelResponse(self.success, output.as_uri(), {"input_tokens": 7}, 0.1)

    async def cancel(self, task_id):
        self.cancelled.append(task_id)


def configured(config_root, tmp_path, **kwargs):
    config = load_config(config_root)
    manifest = config.plugins["xh-tuvan"].model_copy(update={
        "entrypoint": str(Path(__file__).parent / "fixtures" / "process_plugin.py"),
    })
    config = config.model_copy(update={"plugins": {"xh-tuvan": manifest}})
    fake = FakeChannel(tmp_path, **kwargs)
    service = ProcessExecutionService(config, adapter_factory=lambda task, channel: fake)
    return service, fake


def test_real_wrapper_fake_channel_finalizes_task_attempt_cost_artifacts(config_root, tmp_path):
    service, fake = configured(config_root, tmp_path)
    result = asyncio.run(service.execute(envelope(tmp_path)))
    record = service.tasks.get_task("T-BRIDGE")
    assert result.status == record.status == TaskStatus.COMPLETED
    assert service.tasks.get_attempt(record.current_attempt_id).status == TaskStatus.COMPLETED
    assert len(fake.calls) == 1
    assert len(service.artifacts.list_for_task("T-BRIDGE")) == 2
    assert CostRepository(service.database).list_for_task("T-BRIDGE")[0].estimated_usd == 0
    events = service.events.list_for_task("T-BRIDGE")
    assert events[-1].event_type == "TASK_STATUS_CHANGED"
    assert "Test-only analysis" not in str(events)
    assert not list(tmp_path.rglob("context.json"))


@pytest.mark.parametrize("payload,success", [
    ({"outcome": "blocked", "deliverable": "Missing dependency", "evidence": ["fixture"], "blockers": ["dependency"]}, True),
    ({"outcome": "completed"}, True),
    ({"outcome": "completed", "deliverable": "X", "evidence": ["fixture"], "blockers": []}, False),
])
def test_no_false_completion(config_root, tmp_path, payload, success):
    service, fake = configured(config_root, tmp_path, payload=payload, success=success)
    result = asyncio.run(service.execute(envelope(tmp_path)))
    assert result.status == "FAILED"
    assert service.tasks.get_task("T-BRIDGE").status == TaskStatus.FAILED


def test_permission_escalation_requires_approval(config_root, tmp_path):
    service, fake = configured(config_root, tmp_path)
    with pytest.raises(PermissionApprovalRequiredError):
        asyncio.run(service.execute(envelope(tmp_path, permissions={"level": "SYSTEM_WRITE"})))
    assert fake.calls == []
    assert service.tasks.list_tasks() == []


def test_generic_plugin_replaces_xh_tuvan_without_global_changes(config_root, tmp_path):
    service, fake = configured(config_root, tmp_path)
    manifest = service.configuration.plugins["xh-tuvan"].model_copy(update={
        "plugin_id": "unrelated-plugin", "domain": "unrelated",
    })
    service.configuration = service.configuration.model_copy(update={"plugins": {"unrelated-plugin": manifest}})
    result = asyncio.run(service.execute(envelope(tmp_path, plugin="unrelated-plugin")))
    assert result.status == "COMPLETED"
    assert fake.calls[0].prompt_or_instruction == "opaque test request"


def test_duplicate_task_cannot_dispatch_twice(config_root, tmp_path):
    service, fake = configured(config_root, tmp_path)
    asyncio.run(service.execute(envelope(tmp_path)))
    from xh_control.exceptions import DuplicateRecordError
    with pytest.raises(DuplicateRecordError):
        asyncio.run(service.execute(envelope(tmp_path)))
    assert len(fake.calls) == 1


def test_timeout_kills_owned_wrapper_without_channel(tmp_path):
    async def invoke(request):
        raise AssertionError("unexpected channel invocation")
    async def cancel(task_id):
        pass
    adapter = ProcessPluginAdapter(
        (sys.executable, "-c", "import time;time.sleep(60)"),
        {"task_id": "T-BRIDGE"}, tmp_path, invoke, cancel, timeout_seconds=0.3,
    )
    with pytest.raises(PluginResultError):
        asyncio.run(adapter.execute(envelope(tmp_path)))
    assert adapter.active == {}


@pytest.mark.parametrize("mutation", ["wrong-result-task", "invented-usage", "invented-artifact", "domain-learning"])
def test_result_forgery_fails_after_observed_channel_call(config_root, tmp_path, mutation):
    service, fake = configured(config_root, tmp_path)
    with pytest.raises(PluginResultError) as error:
        asyncio.run(service.execute(envelope(tmp_path, user_request=mutation)))
    assert "SECRET-SENTINEL" not in str(error.value)
    assert "SECRET-SENTINEL" not in str(service.events.list_for_task("T-BRIDGE"))
    assert service.tasks.get_task("T-BRIDGE").status == TaskStatus.FAILED
    assert len(fake.calls) == 1


@pytest.mark.parametrize("mutation", ["wrong_task", "wrong_workspace", "wrong_capability", "no_channel", "bad_json", "stderr_secret"])
def test_untrusted_protocol_is_rejected_without_channel_or_secret_audit(tmp_path, mutation):
    task = envelope(tmp_path)
    code = '''import json,sys,pathlib
c=json.loads(pathlib.Path(sys.argv[-1]).read_text())
t=json.loads(sys.stdin.read())
r={"task_id":t["task_id"],"capability":"MASTER","workspace":t["project"]["workspace_uri"],"prompt_or_instruction":"opaque","artifact_refs":[]}
'''
    if mutation.startswith("wrong_"):
        field = {"wrong_task": "task_id", "wrong_workspace": "workspace", "wrong_capability": "capability"}[mutation]
        code += f'r[{field!r}]="wrong"\n'
        code += 'p=pathlib.Path(sys.argv[-1]).parent/"request.pending"\np.write_text(json.dumps(r))\np.replace(p.with_name("request.json"))\nimport time;time.sleep(10)'
    elif mutation == "no_channel":
        code += 'print(json.dumps({"task_id": t["task_id"], "status": "COMPLETED", "outputs": [], "execution_summary": {"elapsed_seconds": 0, "subscription_calls": 1}, "global_learning": {}}))'
    else:
        code += 'print("SECRET-SENTINEL",file=sys.stderr)\nprint("invalid result")'
    calls = []
    async def invoke(request):
        calls.append(request)
        raise AssertionError("must not dispatch")
    async def cancel(task_id):
        pass
    adapter = ProcessPluginAdapter((sys.executable, "-c", code), {"task_id": task.task_id}, tmp_path, invoke, cancel, timeout_seconds=3)
    with pytest.raises((PluginResultError, ValueError)) as error:
        asyncio.run(adapter.execute(task))
    assert "SECRET-SENTINEL" not in str(error.value)
    assert calls == []


def test_cancel_awaits_channel_and_wrapper_exit(config_root, tmp_path):
    service, fake = configured(config_root, tmp_path)
    async def scenario():
        started, released = asyncio.Event(), asyncio.Event()
        async def execute(request):
            started.set()
            await released.wait()
            return ChannelResponse(False, None, {}, 0.1, "CANCELLED")
        async def cancel(task_id):
            released.set()
        fake.execute, fake.cancel = execute, cancel
        work = asyncio.create_task(service.execute(envelope(tmp_path)))
        await asyncio.wait_for(started.wait(), 10)
        transport = service.active["T-BRIDGE"]
        process = transport.active["T-BRIDGE"]
        await service.cancel("T-BRIDGE")
        assert process.returncode is not None
        with pytest.raises(PluginResultError):
            await work
        assert service.tasks.get_task("T-BRIDGE").status == TaskStatus.FAILED
    asyncio.run(scenario())


def test_process_adapter_pause_returns_only_plugin_handoff_uri(tmp_path):
    code = '''import json,sys,time,pathlib
c=json.loads(pathlib.Path(sys.argv[-1]).read_text()); d=pathlib.Path(sys.argv[-1]).parent
t=json.loads(sys.stdin.read())
if c.get("resume_handoff_uri"):
    r={"task_id":t["task_id"],"capability":"MASTER","workspace":t["project"]["workspace_uri"],"prompt_or_instruction":"opaque","artifact_refs":[]}
    (d/"request.json").write_text(json.dumps(r))
    while not (d/"response.json").exists(): time.sleep(.01)
    print(json.dumps({"task_id":t["task_id"],"status":"COMPLETED","outputs":[],"execution_summary":{"elapsed_seconds":0.1,"subscription_calls":1},"global_learning":{}}))
else:
    while not (d/"pause.request.json").exists(): time.sleep(.01)
    pause={"protocol_version":"1.1","task_id":t["task_id"],"handoff_uri":"opaque://handoff/M6"}
    (d/"pause.response.json").write_text(json.dumps(pause))
    print(json.dumps(pause))
'''
    task = envelope(tmp_path)
    async def invoke(request):
        return ChannelResponse(True, None, {}, 0)
    async def cancel(task_id):
        return None
    async def scenario():
        adapter = ProcessPluginAdapter((sys.executable, "-c", code), {"task_id": task.task_id}, tmp_path, invoke, cancel)
        running = asyncio.create_task(adapter.execute(task))
        while not adapter._directories:
            await asyncio.sleep(.01)
        assert await adapter.pause(task.task_id) == "opaque://handoff/M6"
        adapter.complete_pause(task.task_id, True)
        with pytest.raises(PluginPausedSignal):
            await running
        result = await adapter.resume(task, "opaque://handoff/M6")
        assert result.task_id == task.task_id
    asyncio.run(scenario())


def test_process_execution_service_resume_passes_checkpoint_uri_to_bridge(config_root, tmp_path):
    service, fake = configured(config_root, tmp_path)
    task = envelope(tmp_path)
    service.tasks.create_task(task)
    attempt = service.tasks.create_attempt(task.task_id, "pc-main", "codex-subscription")
    service.tasks.transition_task(task.task_id, TaskStatus.QUEUED)
    service.tasks.transition_task(task.task_id, TaskStatus.ASSIGNED, attempt_id=attempt.attempt_id, generation=attempt.generation)
    service.tasks.transition_task(task.task_id, TaskStatus.RUNNING, attempt_id=attempt.attempt_id, generation=attempt.generation)
    service.checkpoint_service.create(
        service.tasks.get_task(task.task_id), attempt_id=attempt.attempt_id,
        generation=attempt.generation, worker_id=attempt.worker_id,
        channel_id=attempt.channel_id, plugin_state_ref="opaque://handoff/M6",
        artifact_refs=[],
    )
    service.tasks.transition_attempt(task.task_id, attempt.attempt_id, attempt.generation, TaskStatus.PAUSED)
    service.tasks.transition_task(task.task_id, TaskStatus.PAUSED, attempt_id=attempt.attempt_id, generation=attempt.generation)
    result = asyncio.run(service.resume(task.task_id))
    assert result.status == "COMPLETED"
    assert fake.calls[0].prompt_or_instruction == "opaque://handoff/M6"
    assert service.tasks.get_task(task.task_id).status == TaskStatus.COMPLETED


def test_process_execution_service_pause_persists_plugin_handoff(config_root, tmp_path):
    service, fake = configured(config_root, tmp_path)
    task = envelope(tmp_path)
    service.tasks.create_task(task)
    attempt = service.tasks.create_attempt(task.task_id, "pc-main", "codex-subscription")
    service.tasks.transition_task(task.task_id, TaskStatus.QUEUED)
    service.tasks.transition_task(task.task_id, TaskStatus.ASSIGNED, attempt_id=attempt.attempt_id, generation=attempt.generation)
    service.tasks.transition_task(task.task_id, TaskStatus.RUNNING, attempt_id=attempt.attempt_id, generation=attempt.generation)

    class SafeTransport:
        completed = None

        async def pause(self, task_id):
            return "opaque://handoff/M6-safe"

        def complete_pause(self, task_id, persisted):
            self.completed = (task_id, persisted)

    transport = SafeTransport()
    service.active[task.task_id] = transport
    asyncio.run(service.pause(task.task_id))
    paused = service.tasks.get_task(task.task_id)
    assert paused.status == TaskStatus.PAUSED
    assert service.tasks.get_attempt(attempt.attempt_id).status == TaskStatus.PAUSED
    assert service.checkpoint_service.load(paused).plugin_state_ref == "opaque://handoff/M6-safe"
    assert transport.completed == (task.task_id, True)
