from datetime import UTC, datetime

from xh_control.channels import ChannelResponse
from xh_control.config import load_config
from xh_control.core import TaskService
from xh_control.learning import OperationalMetricsService
from xh_control.models import TaskEnvelope
from xh_control.state import (
    CostRepository,
    GlobalLearningRepository,
    TaskRepository,
    initialize_database,
)


def envelope(task_id):
    return TaskEnvelope(
        task_id=task_id,
        created_at="2026-09-08T00:00:00Z",
        task_type="generic",
        plugin="xh-tuvan",
        project={"project_id": "P", "workspace_uri": "D:/trial"},
        execution={},
        permissions={},
        budget={"api_soft_usd": 0, "api_hard_usd": 0},
        user_request="opaque",
    )


def test_subscription_metrics_persist_observed_tokens_and_zero_marginal_cost(config_root):
    config = load_config(config_root)
    database = initialize_database(config)
    tasks = TaskService(TaskRepository(database))
    tasks.create_task(envelope("T-METRICS-1"))
    attempt = tasks.create_attempt(
        "T-METRICS-1", "pc-main", "codex-subscription"
    )
    costs = CostRepository(database)
    learning = GlobalLearningRepository(database)
    service = OperationalMetricsService(
        costs,
        learning,
        clock=lambda: datetime(2026, 9, 8, tzinfo=UTC),
        learning_event_id_factory=lambda: "LE-ONE",
    )

    record = service.record_channel_response(
        task_id="T-METRICS-1",
        attempt_id=attempt.attempt_id,
        plugin_id="xh-tuvan",
        capability="MASTER",
        channel=config.channels["codex-subscription"],
        response=ChannelResponse(
            success=True,
            output_ref="file:///trial/output.txt",
            usage={"input_tokens": 13, "cached_input_tokens": 8, "output_tokens": 5},
            latency_seconds=1.25,
        ),
    )

    assert record.estimated_context_tokens == 13
    assert record.estimated_cost_usd == 0
    assert record.latency_seconds == 1.25
    persisted_cost = costs.list_for_task("T-METRICS-1")
    assert len(persisted_cost) == 1
    assert persisted_cost[0].estimated_usd == 0
    assert persisted_cost[0].input_tokens == 13
    assert persisted_cost[0].output_tokens == 5


def test_unknown_api_usage_is_not_fabricated_as_zero(config_root):
    config = load_config(config_root)
    database = initialize_database(config)
    tasks = TaskService(TaskRepository(database))
    tasks.create_task(envelope("T-METRICS-2"))
    attempt = tasks.create_attempt("T-METRICS-2", "pc-main", "codex-subscription")
    channel = config.channels["codex-subscription"].model_copy(
        update={"channel_id": "paid-api", "channel_class": "cheap_api", "billing_mode": "api"}
    )
    costs = CostRepository(database)
    service = OperationalMetricsService(
        costs,
        GlobalLearningRepository(database),
        learning_event_id_factory=lambda: "LE-TWO",
    )

    record = service.record_channel_response(
        task_id="T-METRICS-2",
        attempt_id=attempt.attempt_id,
        plugin_id="generic-plugin",
        capability="MASTER",
        channel=channel,
        response=ChannelResponse(
            success=False,
            output_ref=None,
            usage={},
            latency_seconds=0.5,
            error_type="CHANNEL_PROCESS_FAILED",
        ),
    )

    assert record.estimated_cost_usd is None
    assert record.estimated_context_tokens is None
    assert costs.list_for_task("T-METRICS-2") == []
