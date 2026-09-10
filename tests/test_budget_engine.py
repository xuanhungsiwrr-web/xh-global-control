from datetime import UTC, datetime, timedelta

import pytest

from xh_control.config import load_config
from xh_control.core import BudgetEngine, EventService, TaskService
from xh_control.models import (
    BudgetDecision,
    ChannelClass,
    ChannelHealth,
    ExecutionChannel,
    TaskEnvelope,
    TaskStatus,
)
from xh_control.state import (
    ApprovalRepository,
    CostRepository,
    EventRepository,
    TaskRepository,
    initialize_database,
)

NOW = datetime(2026, 9, 8, 10, 0, tzinfo=UTC)


def execution_channel(channel_id="cheap-api", channel_class=ChannelClass.CHEAP_API):
    return ExecutionChannel(
        channel_id=channel_id,
        provider="test-provider",
        surface="test-surface",
        channel_class=channel_class,
        billing_mode=(
            "api"
            if channel_class in {ChannelClass.CHEAP_API, ChannelClass.PREMIUM_API}
            else channel_class.value
        ),
        capabilities={"MASTER"},
        health=ChannelHealth.AVAILABLE,
    )


def envelope(task_id, *, soft=1.0, hard=3.0):
    return TaskEnvelope(
        task_id=task_id,
        created_at=NOW,
        task_type="generate_report",
        plugin="xh-tuvan",
        project={"project_id": "P", "workspace_uri": "file:///project"},
        execution={},
        permissions={},
        budget={"api_soft_usd": soft, "api_hard_usd": hard},
        user_request="Opaque request",
    )


@pytest.fixture
def budget_services(config_root):
    config = load_config(config_root)
    path = initialize_database(config)
    tasks = TaskService(TaskRepository(path), clock=lambda: NOW)
    events = EventService(EventRepository(path), clock=lambda: NOW)
    costs = CostRepository(path)
    approvals = ApprovalRepository(path)
    engine = BudgetEngine(
        budgets=config.budgets,
        task_service=tasks,
        event_service=events,
        cost_repository=costs,
        approval_repository=approvals,
        clock=lambda: NOW,
        approval_id_factory=lambda: "AP-TEST",
    )
    return path, config, tasks, events, costs, approvals, engine


def create_running(tasks, task_id, *, soft=1.0, hard=3.0):
    tasks.create_task(envelope(task_id, soft=soft, hard=hard))
    for status in (TaskStatus.QUEUED, TaskStatus.ASSIGNED, TaskStatus.RUNNING):
        tasks.transition_task(task_id, status)


@pytest.mark.parametrize(
    "expected,decision",
    [
        (0.0, BudgetDecision.ALLOW),
        (1.0, BudgetDecision.ALLOW),
        (1.0001, BudgetDecision.ALLOW_WITH_WARNING),
        (3.0, BudgetDecision.ALLOW_WITH_WARNING),
    ],
)
def test_soft_and_hard_threshold_edges(budget_services, expected, decision):
    _, _, tasks, _, _, _, engine = budget_services
    create_running(tasks, "T-EDGE")

    result = engine.authorize(
        task_id="T-EDGE",
        channel=execution_channel(),
        expected_cost_usd=expected,
    )

    assert result.decision == decision
    assert result.projected_task_usd == pytest.approx(expected)
    assert tasks.get_task("T-EDGE").status == TaskStatus.RUNNING


def test_hard_budget_requires_approval(budget_services):
    _, _, tasks, events, _, approvals, engine = budget_services
    create_running(tasks, "T-HARD")

    result = engine.authorize(
        task_id="T-HARD",
        channel=execution_channel(),
        expected_cost_usd=3.0001,
    )

    assert result.decision == BudgetDecision.BLOCK_PENDING_APPROVAL
    assert result.approval_id == "AP-TEST"
    assert result.hard_limit_scopes == ("task",)
    assert tasks.get_task("T-HARD").status == TaskStatus.WAITING_APPROVAL
    approval = approvals.get("AP-TEST")
    assert approval.action == "EXCEED_API_HARD_LIMIT"
    assert approval.status == "PENDING"
    assert approval.payload["projected_task_usd"] == pytest.approx(3.0001)
    assert [event.event_type for event in events.list_for_task("T-HARD")][-2:] == [
        "APPROVAL_REQUESTED",
        "TASK_STATUS_CHANGED",
    ]


def test_daily_and_global_monthly_configured_scopes_are_enforced(budget_services):
    _, config, tasks, _, costs, approvals, engine = budget_services
    api = execution_channel()

    create_running(tasks, "T-DAILY", soft=20, hard=20)
    daily = engine.authorize(
        task_id="T-DAILY", channel=api, expected_cost_usd=8.01
    )
    assert daily.decision == BudgetDecision.BLOCK_PENDING_APPROVAL
    assert daily.hard_limit_scopes == ("daily",)
    assert approvals.get("AP-TEST").payload["hard_limit_scopes"] == ["daily"]

    # A fresh engine/database assertion isolates the monthly scope below.
    assert config.budgets.global_budget.monthly_api_hard_usd == 30.0


def test_global_monthly_scope_counts_prior_day_cost(config_root):
    config = load_config(config_root)
    path = initialize_database(config)
    tasks = TaskService(TaskRepository(path), clock=lambda: NOW)
    events = EventService(EventRepository(path), clock=lambda: NOW)
    costs = CostRepository(path)
    approvals = ApprovalRepository(path)
    create_running(tasks, "T-PRIOR", soft=100, hard=100)
    costs.record(
        task_id="T-PRIOR",
        channel_id="cheap-api",
        billing_mode="api",
        estimated_usd=29.5,
        created_at=NOW - timedelta(days=1),
    )
    create_running(tasks, "T-MONTH", soft=10, hard=10)
    engine = BudgetEngine(
        budgets=config.budgets,
        task_service=tasks,
        event_service=events,
        cost_repository=costs,
        approval_repository=approvals,
        clock=lambda: NOW,
        approval_id_factory=lambda: "AP-MONTH",
    )

    result = engine.authorize(
        task_id="T-MONTH",
        channel=execution_channel(),
        expected_cost_usd=1.0,
    )

    assert result.decision == BudgetDecision.BLOCK_PENDING_APPROVAL
    assert result.hard_limit_scopes == ("global_monthly",)
    assert result.projected_daily_usd == pytest.approx(1.0)
    assert result.projected_monthly_usd == pytest.approx(30.5)


@pytest.mark.parametrize(
    "channel_class",
    [ChannelClass.SUBSCRIPTION, ChannelClass.FREE_LOCAL],
)
def test_subscription_and_local_continue_when_paid_action_is_blocked(
    budget_services, channel_class
):
    _, _, tasks, events, _, _, engine = budget_services
    create_running(tasks, "T-CONTINUE")
    blocked = engine.authorize(
        task_id="T-CONTINUE",
        channel=execution_channel(),
        expected_cost_usd=4,
    )
    assert blocked.decision == BudgetDecision.BLOCK_PENDING_APPROVAL

    free_result = engine.authorize(
        task_id="T-CONTINUE",
        channel=execution_channel("free-alternative", channel_class),
        expected_cost_usd=0,
    )

    assert free_result.decision == BudgetDecision.ALLOW
    assert events.list_for_task("T-CONTINUE")[-1].event_type == (
        "NON_PAID_CHANNEL_AUTHORIZED"
    )
    # The paid approval remains visible; callers are still authorized to execute
    # the independent non-paid action while it is pending.
    assert tasks.get_task("T-CONTINUE").status == TaskStatus.WAITING_APPROVAL


def test_actual_cost_and_audit_are_persisted_and_used_for_projection(budget_services):
    _, _, tasks, events, costs, _, engine = budget_services
    create_running(tasks, "T-COST")
    api = execution_channel()
    recorded = engine.record_cost(
        task_id="T-COST",
        channel=api,
        estimated_usd=0.75,
        input_tokens=100,
        output_tokens=50,
    )

    result = engine.authorize(
        task_id="T-COST", channel=api, expected_cost_usd=0.5
    )

    assert recorded.estimated_usd == pytest.approx(0.75)
    assert costs.list_for_task("T-COST") == [recorded]
    assert result.projected_task_usd == pytest.approx(1.25)
    assert result.decision == BudgetDecision.ALLOW_WITH_WARNING
    assert "COST_RECORDED" in [
        event.event_type for event in events.list_for_task("T-COST")
    ]
