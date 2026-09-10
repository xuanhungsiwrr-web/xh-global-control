import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from xh_control.config import load_config
from xh_control.models import (ExecutionChannel, GlobalLearningSummary, PluginManifest,
                               PluginResult, TaskEnvelope, TaskRecord)


def envelope():
    return dict(task_id="T-1", created_at="2026-09-08T00:00:00Z", task_type="generic",
                plugin="generic-plugin", project={"project_id": "P-1", "workspace_uri": "file:///project"},
                execution={}, permissions={}, budget={"api_soft_usd": 1, "api_hard_usd": 3},
                user_request="Opaque request passed to plugin")


def test_task_envelope_validation():
    task = TaskEnvelope.model_validate(envelope())
    assert task.execution.master_preference == "AUTO"
    assert task.execution.cost_mode == "BALANCED"
    assert TaskRecord(task=task, status="CREATED").latest_checkpoint_uri is None
    for patch in ({"task_id": ""}, {"created_at": "bad"}, {"permissions": {"level": "ADMIN"}},
                  {"budget": {"api_soft_usd": 4, "api_hard_usd": 1}},
                  {"budget": {"api_soft_usd": 0, "api_hard_usd": float("inf")}}):
        with pytest.raises(ValidationError):
            TaskEnvelope.model_validate(envelope() | patch)


def test_plugin_manifest_validation():
    manifest = load_config().plugins["xh-tuvan"].model_dump()
    manifest.update(plugin_id="generic-plugin", domain="generic", accepted_task_types={"generic"})
    assert PluginManifest(**manifest).owns_domain_workflow
    for patch in ({"plugin_id": ""}, {"owns_domain_workflow": False},
                  {"allowed_global_learning_fields": {"engineering_rule"}}):
        with pytest.raises(ValidationError):
            PluginManifest(**(manifest | patch))


def test_execution_channel_validation():
    channel = load_config().channels["codex-subscription"].model_dump()
    assert ExecutionChannel(**channel).health == "UNKNOWN"
    for patch in ({"channel_class": "provider"}, {"health": "UP"}, {"capabilities": []},
                  {"estimated_input_usd_per_mtoken": -1}):
        with pytest.raises(ValidationError):
            ExecutionChannel(**(channel | patch))


@pytest.mark.parametrize("key", ["engineering_rule", "legal_rule", "technical_rule", "technical_standard",
    "report_structure", "report_section_rule", "report_rule", "writing_rule", "chapter_rule",
    "construction_workflow_rule", "domain_knowledge", "domain_learning"])
@pytest.mark.parametrize("nested", [False, True])
def test_domain_learning_rejected_from_global(key, nested):
    assert key not in GlobalLearningSummary.model_fields
    payload = {"routing": [{"metrics": [{key: "forbidden"}]}]} if nested else {key: []}
    with pytest.raises(ValidationError):
        PluginResult(task_id="T", status="COMPLETED", execution_summary={"elapsed_seconds": 1}, global_learning=payload)


def test_operational_learning_and_result():
    result = PluginResult(task_id="T", status="COMPLETED", execution_summary={"elapsed_seconds": 1},
                          global_learning={"model_performance": [{"channel": "codex-subscription", "success": True}]})
    assert result.execution_summary.api_spend_usd == 0


@pytest.mark.parametrize("name,model", [("task-envelope", TaskEnvelope), ("plugin-manifest", PluginManifest), ("plugin-result", PluginResult)])
def test_published_schemas_match_contracts(name, model):
    path = Path(__file__).resolve().parents[1] / "schemas" / f"{name}.schema.json"
    assert json.loads(path.read_text()) == model.model_json_schema()
