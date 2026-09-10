"""In-memory registry for validated domain-plugin adapters."""

from dataclasses import dataclass

from xh_control.exceptions import (
    PluginNotFoundError,
    PluginRegistrationError,
    PluginTaskTypeError,
)
from xh_control.models import PluginManifest, TaskEnvelope

from .base import DomainPluginAdapter

SUPPORTED_PLUGIN_INTERFACE_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class PluginRegistration:
    """A validated manifest and its adapter implementation."""

    manifest: PluginManifest
    adapter: DomainPluginAdapter


class PluginRegistry:
    """Resolve plugins without importing or interpreting their domain workflow."""

    def __init__(self, interface_version: str = SUPPORTED_PLUGIN_INTERFACE_VERSION) -> None:
        if not interface_version:
            raise ValueError("interface_version must not be empty")
        self.interface_version = interface_version
        self._plugins: dict[str, PluginRegistration] = {}

    def register(
        self,
        manifest: PluginManifest,
        adapter: DomainPluginAdapter,
    ) -> PluginRegistration:
        if not isinstance(manifest, PluginManifest):
            raise PluginRegistrationError("plugin manifest must satisfy PluginManifest")
        if not isinstance(adapter, DomainPluginAdapter):
            raise PluginRegistrationError("plugin adapter must implement DomainPluginAdapter")
        if manifest.interface_version != self.interface_version:
            raise PluginRegistrationError(
                f"Plugin {manifest.plugin_id} uses interface {manifest.interface_version}; "
                f"Global supports {self.interface_version}"
            )
        if manifest.plugin_id in self._plugins:
            raise PluginRegistrationError(f"Plugin already registered: {manifest.plugin_id}")
        registration = PluginRegistration(manifest=manifest, adapter=adapter)
        self._plugins[manifest.plugin_id] = registration
        return registration

    def resolve(self, plugin_id: str) -> PluginRegistration:
        try:
            return self._plugins[plugin_id]
        except KeyError:
            raise PluginNotFoundError(f"Plugin not registered: {plugin_id}") from None

    def resolve_for_task(self, task: TaskEnvelope) -> PluginRegistration:
        registration = self.resolve(task.plugin)
        if task.task_type not in registration.manifest.accepted_task_types:
            raise PluginTaskTypeError(
                f"Plugin {task.plugin} does not accept task type {task.task_type}"
            )
        return registration

    def list_manifests(self) -> tuple[PluginManifest, ...]:
        return tuple(
            registration.manifest
            for _, registration in sorted(self._plugins.items())
        )
