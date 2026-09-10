"""Run the real M4 process path in an isolated evidence database.

The operator supplies the authorized project and task. This script does not
assert domain acceptance: inspect the plugin artifact and requested criteria.
"""
import argparse
import asyncio
from datetime import datetime, UTC
import json
from pathlib import Path
from uuid import uuid4

from xh_control.config import load_config
from xh_control.core.process_execution_service import ProcessExecutionService
from xh_control.models import TaskEnvelope


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()
    config = load_config()
    root = args.evidence_root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    config = config.model_copy(update={"system": config.system.model_copy(update={
        "sqlite_path": str(root / "control.db"), "artifact_root": str(root / "artifacts"),
    })})
    budget = config.budgets.plugins["xh-tuvan"]
    task = TaskEnvelope(
        task_id="T-M4-BRIDGE-" + uuid4().hex[:12].upper(), created_at=datetime.now(UTC),
        plugin="xh-tuvan", task_type="analyze_project",
        project={"project_id": args.workspace.name, "workspace_uri": str(args.workspace.resolve())},
        execution={"master_preference": "AUTO", "cost_mode": "BALANCED"},
        permissions={"level": "SAFE_EDIT"},
        budget={"api_soft_usd": budget.task_api_soft_usd, "api_hard_usd": budget.task_api_hard_usd},
        user_request=args.request,
    )
    (root / "task.json").write_text(task.model_dump_json(indent=2), encoding="utf-8")
    service = ProcessExecutionService(config)
    try:
        result = asyncio.run(service.execute(task))
    except Exception:
        print(json.dumps({"task_id": task.task_id, "outcome": "EXECUTION_FAILED"}))
        return 3
    (root / "result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(result.model_dump_json(indent=2))
    return 0 if result.status == "COMPLETED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
