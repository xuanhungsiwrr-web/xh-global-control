import inspect

import pytest

from xh_control.exceptions import (
    PluginNotFoundError,
    PluginRegistrationError,
    PluginTaskTypeError,
    PluginUnavailableError,
)
from xh_control.models import PluginManifest, PluginResult, TaskEnvelope
from xh_control.plugins import DomainPluginAdapter, PluginRegistry, XHTuvanAdapter


def run_immediate(coroutine):
    """Drive an I/O-free test coroutine without creating a Windows socket loop."""
    try:
        coroutine.send(None)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("mock coroutine unexpectedly suspended")


class StaticAdapter(DomainPluginAdapter):
    def __init__(self, result=None, *, healthy=True):
        self.result = result
        self.healthy = healthy
        self.executed_tasks = []

    async def healthcheck(self) -> bool:
        return self.healthy

    async def execute(self, task: TaskEnvelope) -> PluginResult:
        self.executed_tasks.append(task)
        return self.result

    async def pause(self, task_id: str) -> str:
        return "opaque://handoff"

    async def resume(self, task: TaskEnvelope, handoff_uri: str) -> PluginResult:
        return self.result

    async def cancel(self, task_id: str) -> None:
        return None


def manifest(**patch):
    values = {
        "plugin_id": "generic-plugin",
        "version": "1.0.0",
        "interface_version": "1.0",
        "domain": "generic",
        "entrypoint_type": "mock",
        "entrypoint": "tests.StaticAdapter",
        "accepted_task_types": {"generic"},
    }
    return PluginManifest(**(values | patch))


def task(**patch):
    values = {
        "task_id": "T-PLUGIN-1",
        "created_at": "2026-09-08T00:00:00Z",
        "task_type": "generic",
        "plugin": "generic-plugin",
        "project": {"project_id": "P-1", "workspace_uri": "file:///project"},
        "execution": {},
        "permissions": {},
        "budget": {"api_soft_usd": 1, "api_hard_usd": 3},
        "user_request": "Opaque request",
    }
    return TaskEnvelope(**(values | patch))


def test_domain_plugin_adapter_signatures_are_stable():
    assert list(inspect.signature(DomainPluginAdapter.healthcheck).parameters) == ["self"]
    assert list(inspect.signature(DomainPluginAdapter.execute).parameters) == ["self", "task"]
    assert list(inspect.signature(DomainPluginAdapter.pause).parameters) == ["self", "task_id"]
    assert list(inspect.signature(DomainPluginAdapter.resume).parameters) == ["self", "task", "handoff_uri"]
    assert list(inspect.signature(DomainPluginAdapter.cancel).parameters) == ["self", "task_id"]


def test_registry_resolves_only_compatible_registered_plugins_and_task_types():
    registry = PluginRegistry()
    adapter = StaticAdapter()
    registration = registry.register(manifest(), adapter)
    assert registry.resolve("generic-plugin") == registration
    assert registry.resolve_for_task(task()) == registration
    assert registry.list_manifests() == (registration.manifest,)

    with pytest.raises(PluginNotFoundError):
        registry.resolve("missing-plugin")
    with pytest.raises(PluginTaskTypeError):
        registry.resolve_for_task(task(task_type="unsupported"))
    with pytest.raises(PluginRegistrationError, match="interface 9.0"):
        PluginRegistry().register(manifest(plugin_id="future", interface_version="9.0"), adapter)
    with pytest.raises(PluginRegistrationError, match="already registered"):
        registry.register(manifest(), StaticAdapter())
    with pytest.raises(PluginRegistrationError, match="DomainPluginAdapter"):
        PluginRegistry().register(manifest(), object())


def test_xh_tuvan_adapter_reports_verified_bridge_blocker():
    adapter = XHTuvanAdapter()
    assert run_immediate(adapter.healthcheck()) is False
    with pytest.raises(PluginUnavailableError, match="ACR-001"):
        run_immediate(adapter.execute(task(plugin="xh-tuvan", task_type="generate_report")))
    with pytest.raises(PluginUnavailableError, match="ACR-001"):
        run_immediate(adapter.pause("T-1"))
    with pytest.raises(PluginUnavailableError, match="ACR-001"):
        run_immediate(adapter.resume(task(plugin="xh-tuvan", task_type="generate_report"), "opaque://handoff"))
    with pytest.raises(PluginUnavailableError, match="ACR-001"):
        run_immediate(adapter.cancel("T-1"))
