"""Explicit local M4 runner: input envelope is already approved by the operator."""

import argparse
import asyncio
from pathlib import Path
import sys

from xh_control.config import load_config
from xh_control.core.process_execution_service import ProcessExecutionService
from xh_control.models import TaskEnvelope


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-root", type=Path)
    parser.add_argument("--envelope", type=Path, required=True)
    args = parser.parse_args()
    try:
        task = TaskEnvelope.model_validate_json(args.envelope.read_bytes())
        service = ProcessExecutionService(load_config(args.config_root))
        result = asyncio.run(service.execute(task))
        print(result.model_dump_json())
        return 0 if result.status == "COMPLETED" else 3
    except Exception:
        print("M4_PROCESS_EXECUTION_FAILED", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
