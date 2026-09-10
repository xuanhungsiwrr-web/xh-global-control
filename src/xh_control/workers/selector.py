"""Deterministic capability-first worker selection."""

from collections.abc import Mapping

from xh_control.config import WorkerConfig
from xh_control.exceptions import NoEligibleWorkerError


class WorkerSelector:
    """Select an enabled worker only when every required capability is real."""

    def __init__(self, workers: Mapping[str, WorkerConfig]) -> None:
        self.workers = dict(workers)

    def select(self, required_capabilities: set[str]) -> str:
        required = set(required_capabilities)
        candidates = [
            (worker_id, worker)
            for worker_id, worker in self.workers.items()
            if worker.enabled and required <= set(worker.capabilities)
        ]
        if not candidates:
            enabled = [
                (worker_id, worker)
                for worker_id, worker in sorted(self.workers.items())
                if worker.enabled
            ]
            if enabled:
                details = "; ".join(
                    f"{worker_id} missing: "
                    + (", ".join(sorted(required - set(worker.capabilities))) or "<none>")
                    for worker_id, worker in enabled
                )
            else:
                details = "no workers are enabled"
            raise NoEligibleWorkerError(
                f"No enabled worker provides all required capabilities; {details}"
            )
        candidates.sort(key=lambda item: (-item[1].priority, item[0]))
        return candidates[0][0]
