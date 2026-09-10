from datetime import UTC, datetime, timedelta

import pytest

from xh_control.config import load_config
from xh_control.exceptions import NoEligibleChannelError
from xh_control.models import (
    ChannelClass,
    ChannelHealth,
    ChannelHealthRecord,
    CostMode,
    ExecutionChannel,
    MasterPreference,
    TaskEnvelope,
)
from xh_control.routing import ChannelRouter
from xh_control.state import ChannelHealthRepository, initialize_database

NOW = datetime(2026, 9, 8, 4, 0, tzinfo=UTC)


def channel(
    channel_id,
    channel_class,
    *,
    provider="test",
    surface="test",
    model=None,
    health=ChannelHealth.AVAILABLE,
    capabilities=frozenset({"MASTER"}),
    priority=100,
    metadata=None,
):
    return ExecutionChannel(
        channel_id=channel_id,
        provider=provider,
        surface=surface,
        model=model,
        channel_class=channel_class,
        billing_mode=("subscription" if channel_class == ChannelClass.SUBSCRIPTION else "api"),
        capabilities=set(capabilities),
        health=health,
        priority=priority,
        metadata=metadata or {},
    )


def task(
    *,
    preference=MasterPreference.AUTO,
    mode=CostMode.BALANCED,
    capability="MASTER",
):
    return TaskEnvelope(
        task_id="T-ROUTE",
        created_at=NOW,
        task_type="generic",
        plugin="generic-plugin",
        project={"project_id": "P", "workspace_uri": "file:///project"},
        execution={
            "master_capability": capability,
            "master_preference": preference,
            "cost_mode": mode,
        },
        permissions={},
        budget={"api_soft_usd": 1, "api_hard_usd": 3},
        user_request="Opaque request",
    )


def with_channels(config_root, *channels):
    config = load_config(config_root)
    return config.model_copy(
        update={"channels": {item.channel_id: item for item in channels}}
    )


def test_subscription_channel_beats_api_when_capable(config_root):
    subscription = channel(
        "claude-code-subscription",
        ChannelClass.SUBSCRIPTION,
        provider="anthropic",
        surface="claude_code",
        health=ChannelHealth.DEGRADED,
        metadata={"quality_score": 0.1, "reliability_score": 0.1},
    )
    paid_api = channel(
        "premium-api",
        ChannelClass.PREMIUM_API,
        provider="openai",
        metadata={"quality_score": 100, "reliability_score": 100},
    )
    router = ChannelRouter(with_channels(config_root, paid_api, subscription))

    selected = router.resolve_master_channel(task=task(), worker_id="pc-main")

    assert selected.channel_id == "claude-code-subscription"
    assert selected.channel_class == ChannelClass.SUBSCRIPTION


def test_unhealthy_subscription_is_skipped(config_root):
    unavailable = channel(
        "claude-code-subscription",
        ChannelClass.SUBSCRIPTION,
        provider="anthropic",
        health=ChannelHealth.UNAVAILABLE,
    )
    paid_api = channel("cheap-api", ChannelClass.CHEAP_API)
    router = ChannelRouter(with_channels(config_root, unavailable, paid_api))

    assert router.resolve_master_channel(
        task=task(), worker_id="pc-main"
    ).channel_id == "cheap-api"


def test_default_channel_class_order_is_hard_and_capability_first(config_root):
    channels = (
        channel("premium", ChannelClass.PREMIUM_API, priority=10000),
        channel("cheap", ChannelClass.CHEAP_API, priority=9000),
        channel("local", ChannelClass.FREE_LOCAL, priority=1),
        channel("subscription", ChannelClass.SUBSCRIPTION, priority=0),
    )
    ranked = ChannelRouter(with_channels(config_root, *channels)).rank_candidates(
        task=task(), worker_id="pc-main"
    )

    assert [item.channel.channel_id for item in ranked] == [
        "subscription",
        "local",
        "cheap",
        "premium",
    ]


def test_disabled_and_incapable_channels_are_filtered(config_root):
    disabled = channel("disabled", ChannelClass.SUBSCRIPTION).model_copy(
        update={"enabled": False}
    )
    incapable = channel(
        "incapable", ChannelClass.SUBSCRIPTION, capabilities={"CODING"}
    )
    eligible = channel("eligible", ChannelClass.CHEAP_API)
    ranked = ChannelRouter(
        with_channels(config_root, disabled, incapable, eligible)
    ).rank_candidates(task=task(), worker_id="pc-main")

    assert [item.channel.channel_id for item in ranked] == ["eligible"]


def test_master_preferences_choose_corresponding_subscription_and_fallback(config_root):
    claude = channel(
        "claude-code-subscription", ChannelClass.SUBSCRIPTION, provider="anthropic"
    )
    codex = channel(
        "codex-subscription", ChannelClass.SUBSCRIPTION, provider="openai", priority=999
    )
    router = ChannelRouter(with_channels(config_root, codex, claude))

    assert router.resolve_master_channel(
        task=task(preference=MasterPreference.CLAUDE), worker_id="pc-main"
    ).channel_id == "claude-code-subscription"
    assert router.resolve_master_channel(
        task=task(preference=MasterPreference.CHATGPT), worker_id="pc-main"
    ).channel_id == "codex-subscription"

    unavailable_claude = claude.model_copy(
        update={"health": ChannelHealth.UNAVAILABLE}
    )
    fallback = ChannelRouter(with_channels(config_root, unavailable_claude, codex))
    assert fallback.resolve_master_channel(
        task=task(preference=MasterPreference.CLAUDE), worker_id="pc-main"
    ).channel_id == "codex-subscription"

    incapable_claude = claude.model_copy(update={"capabilities": {"CODING"}})
    incapable_fallback = ChannelRouter(
        with_channels(config_root, incapable_claude, codex)
    )
    assert incapable_fallback.resolve_master_channel(
        task=task(preference=MasterPreference.CLAUDE), worker_id="pc-main"
    ).channel_id == "codex-subscription"


def test_master_cross_provider_fallback_obeys_policy(config_root):
    unavailable_claude = channel(
        "claude-code-subscription",
        ChannelClass.SUBSCRIPTION,
        provider="anthropic",
        health=ChannelHealth.UNAVAILABLE,
    )
    codex = channel(
        "codex-subscription", ChannelClass.SUBSCRIPTION, provider="openai"
    )
    anthropic_api = channel(
        "anthropic-api", ChannelClass.CHEAP_API, provider="anthropic"
    )
    config = with_channels(config_root, unavailable_claude, codex, anthropic_api)
    fallback = config.routing.fallback.model_copy(
        update={"allow_cross_provider": False}
    )
    config = config.model_copy(
        update={
            "routing": config.routing.model_copy(update={"fallback": fallback})
        }
    )

    selected = ChannelRouter(config).resolve_master_channel(
        task=task(preference=MasterPreference.CLAUDE), worker_id="pc-main"
    )

    assert selected.channel_id == "anthropic-api"


@pytest.mark.parametrize(
    "mode,eligible",
    [
        (CostMode.ECONOMY, False),
        (CostMode.BALANCED, True),
        (CostMode.MAX_QUALITY, True),
    ],
)
def test_mode_restrictions_follow_config(config_root, mode, eligible):
    router = ChannelRouter(
        with_channels(config_root, channel("premium", ChannelClass.PREMIUM_API))
    )
    if not eligible:
        with pytest.raises(NoEligibleChannelError):
            router.resolve_master_channel(task=task(mode=mode), worker_id="pc-main")
    else:
        assert router.resolve_master_channel(
            task=task(mode=mode), worker_id="pc-main"
        ).channel_id == "premium"


def test_no_eligible_channel_is_explicit(config_root):
    router = ChannelRouter(
        with_channels(
            config_root,
            channel(
                "incapable",
                ChannelClass.SUBSCRIPTION,
                capabilities={"CODING"},
            ),
        )
    )

    with pytest.raises(NoEligibleChannelError, match="capability MASTER"):
        router.resolve_master_channel(task=task(), worker_id="pc-main")


def test_cooldown_skips_only_the_affected_channel_model(config_root):
    config = with_channels(
        config_root,
        channel(
            "codex-model-a",
            ChannelClass.SUBSCRIPTION,
            provider="openai",
            model="model-a",
        ),
        channel(
            "codex-model-b",
            ChannelClass.SUBSCRIPTION,
            provider="openai",
            model="model-b",
        ),
        channel("cheap-api", ChannelClass.CHEAP_API),
    )
    health = ChannelHealthRepository(initialize_database(config))
    health.upsert(
        ChannelHealthRecord(
            channel_id="codex-model-a",
            health=ChannelHealth.AVAILABLE,
            cooldown_until=NOW + timedelta(minutes=30),
            metadata={"model": "model-a", "reason": "rate_limit"},
        )
    )
    health.upsert(
        ChannelHealthRecord(
            channel_id="codex-model-b",
            health=ChannelHealth.AVAILABLE,
            metadata={"model": "model-b"},
        )
    )
    router = ChannelRouter(config, health_repository=health, clock=lambda: NOW)

    ranked = router.rank_candidates(task=task(), worker_id="pc-main")

    assert [item.channel.channel_id for item in ranked] == ["codex-model-b", "cheap-api"]


def test_unknown_is_not_scored_as_healthy_and_handoff_penalty_is_deterministic(config_root):
    unknown = channel(
        "a-unknown", ChannelClass.SUBSCRIPTION, health=ChannelHealth.UNKNOWN
    )
    available = channel("z-available", ChannelClass.SUBSCRIPTION)
    router = ChannelRouter(with_channels(config_root, unknown, available))

    ranked = router.rank_candidates(task=task(), worker_id="pc-main")
    assert ranked[0].channel.channel_id == "z-available"
    assert ranked[1].effective_health == ChannelHealth.UNKNOWN

    first = channel("a-first", ChannelClass.SUBSCRIPTION)
    second = channel("z-second", ChannelClass.SUBSCRIPTION)
    handoff_router = ChannelRouter(with_channels(config_root, first, second))
    selected = handoff_router.resolve_master_channel(
        task=task(), worker_id="pc-main", current_channel_id="z-second"
    )
    assert selected.channel_id == "z-second"
