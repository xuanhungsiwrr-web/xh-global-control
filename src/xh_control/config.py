"""Offline configuration contracts and deterministic YAML loading."""

from pathlib import Path
from typing import Annotated, Literal
import json

import yaml
from pydantic import Field, ValidationError, model_validator

from .constants import DEFAULT_CONFIG_ROOT, EXPECTED_CONFIG_ROOTS
from .exceptions import ConfigurationError
from .models import (ChannelClass, CostMode, ExecutionChannel, MasterPreference,
                     PermissionLevel, PluginManifest, TaskBudget)
from .models.base import ContractModel

Name = Annotated[str, Field(min_length=1)]
Money = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class ConfigModel(ContractModel):
    model_config = {"extra": "forbid", "strict": True, "allow_inf_nan": False}


class Infrastructure(ConfigModel):
    adapter: Name


class SystemConfig(ConfigModel):
    name: Name
    environment: Name
    default_cost_mode: CostMode
    default_master: MasterPreference
    subscription_first: bool
    state_backend: Literal["sqlite"]
    sqlite_path: Name
    infrastructure: Infrastructure
    artifact_root: Name


class ModeConfig(ConfigModel):
    premium_api_allowed: bool
    cross_review_allowed: bool
    api_escalation_threshold: Literal["high", "medium", "low"]


class Weights(ConfigModel):
    capability_fit: float
    subscription_bonus: float
    quality: float
    reliability: float
    worker_affinity: float
    monetary_cost: float
    token_cost: float
    latency: float
    handoff_penalty: float


class Fallback(ConfigModel):
    max_retries_same_channel: int = Field(ge=0)
    allow_cross_provider: bool


class RoutingConfig(ConfigModel):
    class_priority: dict[ChannelClass, int]
    weights: Weights
    modes: dict[CostMode, ModeConfig]
    fallback: Fallback

    @model_validator(mode="after")
    def complete_modes_and_classes(self) -> "RoutingConfig":
        if set(self.class_priority) != set(ChannelClass) or set(self.modes) != set(CostMode):
            raise ValueError("class_priority and modes must contain every channel class and cost mode")
        return self


class HealthPolicy(ConfigModel):
    rate_limit_cooldown_minutes: int = Field(ge=0)


class SubscriptionConfig(ConfigModel):
    enabled: bool
    preferred_channel: Name
    health_policy: HealthPolicy


class GlobalBudget(ConfigModel):
    monthly_api_hard_usd: Money


class DefaultBudget(ConfigModel):
    task_api_soft_usd: Money
    task_api_hard_usd: Money

    @model_validator(mode="after")
    def ordered_limits(self) -> "DefaultBudget":
        if self.task_api_soft_usd > self.task_api_hard_usd:
            raise ValueError("task_api_hard_usd must be at least task_api_soft_usd")
        return self


class BudgetsConfig(ConfigModel):
    global_budget: GlobalBudget = Field(alias="global")
    daily: TaskBudget
    defaults: DefaultBudget
    plugins: dict[Name, DefaultBudget]


class WorkerPaths(ConfigModel):
    git_root: Name
    project_root: Name


class WorkerConfig(ConfigModel):
    hostname: Name
    enabled: bool
    priority: int
    capabilities: list[Name] = Field(min_length=1)
    paths: WorkerPaths


class PermissionFlags(ConfigModel):
    read_project: bool
    write_temp: bool
    write_project: bool
    modify_system: bool
    approval_required: bool = False


class PrivilegedPermission(ConfigModel):
    approval_required: Literal["always"]


class PermissionsConfig(ConfigModel):
    default_level: PermissionLevel
    levels: dict[PermissionLevel, PermissionFlags | PrivilegedPermission]

    @model_validator(mode="after")
    def complete_levels(self) -> "PermissionsConfig":
        if set(self.levels) != set(PermissionLevel):
            raise ValueError("levels must define every permission level")
        if not isinstance(self.levels[PermissionLevel.PRIVILEGED], PrivilegedPermission):
            raise ValueError("PRIVILEGED requires approval_required: always")
        system = self.levels[PermissionLevel.SYSTEM_WRITE]
        if not isinstance(system, PermissionFlags) or not system.approval_required:
            raise ValueError("SYSTEM_WRITE requires approval_required: true")
        for level, flags in self.levels.items():
            if level != PermissionLevel.PRIVILEGED and not isinstance(flags, PermissionFlags):
                raise ValueError("non-privileged levels require all permission flags")
        return self


class Configuration(ContractModel):
    config_root: Path
    system: SystemConfig
    routing: RoutingConfig
    channels: dict[Name, ExecutionChannel] = Field(min_length=1)
    subscriptions: dict[Name, SubscriptionConfig]
    budgets: BudgetsConfig
    plugins: dict[Name, PluginManifest] = Field(min_length=1)
    workers: dict[Name, WorkerConfig] = Field(min_length=1)
    permissions: PermissionsConfig

    @property
    def database_path(self) -> Path:
        """Relative runtime paths are relative to the config root's parent."""
        return (self.config_root.parent / self.system.sqlite_path).resolve()

    @model_validator(mode="after")
    def references_exist(self) -> "Configuration":
        for subscription in self.subscriptions.values():
            channel = self.channels.get(subscription.preferred_channel)
            if channel is None or channel.channel_class != ChannelClass.SUBSCRIPTION:
                raise ValueError("subscriptions.preferred_channel must reference a subscription channel")
        for key, manifest in self.plugins.items():
            if key != manifest.plugin_id:
                raise ValueError("plugins mapping key must match plugin_id")
        if self.budgets.plugins.keys() - self.plugins.keys():
            raise ValueError("budgets.plugins must reference configured plugins")
        return self


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate keys rather than silently replacing configuration."""


def _mapping(loader: UniqueKeyLoader, node: yaml.MappingNode) -> dict:
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise ValueError("mapping keys must be unique strings")
        result[key] = loader.construct_object(value_node)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def load_config(config_root: Path | str | None = None) -> Configuration:
    """Read all eight files without executing plugins or contacting services."""
    root = Path(config_root).resolve() if config_root is not None else DEFAULT_CONFIG_ROOT
    data: dict = {"config_root": root}
    for filename, key in EXPECTED_CONFIG_ROOTS.items():
        path = root / filename
        try:
            document = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
        except (OSError, UnicodeError, yaml.YAMLError, ValueError) as exc:
            # Never include YAML source lines or supplied values in diagnostics.
            raise ConfigurationError(f"{path}: cannot read valid YAML ({type(exc).__name__}); check file syntax and unique keys") from None
        if not isinstance(document, dict) or set(document) != {key} or not isinstance(document[key], dict):
            raise ConfigurationError(f"{path}: expected exactly one '{key}' mapping")
        data[key] = document[key]
    for key, value in data["channels"].items():
        if isinstance(value, dict):
            if "channel_id" in value and value["channel_id"] != key:
                raise ConfigurationError("channels.yaml: channel_id must match its mapping key")
            value["channel_id"] = key
    try:
        # JSON validation accepts enum strings while retaining strict scalar typing.
        return Configuration.model_validate_json(json.dumps(data, default=str), strict=True)
    except ValidationError as exc:
        locations = [".".join(map(str, error["loc"])) + ": " + error["type"] for error in exc.errors()]
        raise ConfigurationError(f"{root}: invalid configuration at " + "; ".join(locations)) from None
    except (ValueError, RecursionError):
        raise ConfigurationError(f"{root}: configuration must not contain cyclic YAML aliases") from None
