import sqlite3

from xh_control.config import load_config
from xh_control.models import (
    ChannelClass,
    ChannelHealth,
    ChannelHealthRecord,
    ExecutionChannel,
    TaskEnvelope,
)
from xh_control.routing import ChannelRouter
from xh_control.state import ChannelHealthRepository, initialize_database


def test_both_healthy_subscriptions_prevent_paid_api_selection(config_root):
    config = load_config(config_root)
    paid = ExecutionChannel(
        channel_id="openai-api-premium",
        provider="openai",
        surface="api",
        model="premium-test-model",
        channel_class=ChannelClass.PREMIUM_API,
        billing_mode="api",
        capabilities={"MASTER"},
        enabled=True,
        priority=10000,
        health=ChannelHealth.AVAILABLE,
        metadata={"quality_score": 10000, "reliability_score": 10000},
    )
    config = config.model_copy(
        update={"channels": {**config.channels, paid.channel_id: paid}}
    )
    path = initialize_database(config)
    health = ChannelHealthRepository(path)
    for channel_id in ("claude-code-subscription", "codex-subscription"):
        health.upsert(
            ChannelHealthRecord(
                channel_id=channel_id,
                health=ChannelHealth.AVAILABLE,
                metadata={"source": "simulated_m3_acceptance"},
            )
        )
    task = TaskEnvelope(
        task_id="T-M3-ACCEPT",
        created_at="2026-09-08T00:00:00Z",
        task_type="generic",
        plugin="generic-plugin",
        project={"project_id": "P", "workspace_uri": "file:///project"},
        execution={},
        permissions={},
        budget={"api_soft_usd": 1, "api_hard_usd": 3},
        user_request="Opaque request",
    )

    selected = ChannelRouter(config, health_repository=health).resolve_master_channel(
        task=task,
        worker_id="pc-main",
    )

    assert selected.channel_id in {
        "claude-code-subscription",
        "codex-subscription",
    }
    assert selected.channel_class == ChannelClass.SUBSCRIPTION
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM cost_events").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM approvals").fetchone() == (0,)
