from pathlib import Path

import pytest

from xh_control.config import WorkerConfig, load_config
from xh_control.exceptions import NoEligibleWorkerError
from xh_control.workers import WorkerSelector


def worker(*, enabled=True, priority=100, capabilities=("filesystem",)):
    return WorkerConfig(
        hostname="test-host",
        enabled=enabled,
        priority=priority,
        capabilities=list(capabilities),
        paths={"git_root": "D:/test", "project_root": "D:/test"},
    )


def test_pc_main_matches_real_required_filesystem_capability():
    config = load_config()

    assert WorkerSelector(config.workers).select({"filesystem"}) == "pc-main"
    assert config.workers["pc-main"].hostname == "TRINITY-X1"
    assert Path(config.workers["pc-main"].paths.git_root).is_dir()
    assert Path(config.workers["pc-main"].paths.project_root).is_dir()
    assert "claude_code" not in config.workers["pc-main"].capabilities


def test_real_xh_tuvan_manifest_uses_approved_process_bridge():
    config = load_config()
    required = config.plugins["xh-tuvan"].required_global_capabilities

    assert config.plugins["xh-tuvan"].version == "0.7.3"
    assert config.plugins["xh-tuvan"].entrypoint_type == "process"
    assert "python" in required
    assert WorkerSelector(config.workers).select(required) == "pc-main"


def test_missing_capability_is_rejected_instead_of_assumed():
    selector = WorkerSelector({"pc-main": worker(capabilities=("filesystem",))})

    with pytest.raises(NoEligibleWorkerError, match="office"):
        selector.select({"filesystem", "office"})


def test_disabled_worker_is_not_selected_and_ties_are_deterministic():
    selector = WorkerSelector(
        {
            "z-worker": worker(priority=10),
            "a-worker": worker(priority=10),
            "disabled": worker(enabled=False, priority=999),
        }
    )

    assert selector.select(set()) == "a-worker"
