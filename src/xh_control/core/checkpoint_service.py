"""Artifact-first checkpoint persistence and compatibility validation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import uuid4

from xh_control.exceptions import CheckpointError, CheckpointIncompatibleError
from xh_control.models import GlobalCheckpoint, TaskRecord

from .artifact_service import ArtifactService


def _now() -> datetime:
    return datetime.now(UTC)


def _local_path(uri: str) -> Path | None:
    # urlparse treats ``C:/...`` as a URI scheme on Windows.
    if len(uri) >= 2 and uri[1] == ":":
        return Path(uri)
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        return Path(unquote(parsed.path))
    if parsed.scheme:
        return None
    return Path(uri)


class CheckpointService:
    """Write/read numbered checkpoint documents without storing their contents in SQLite."""

    def __init__(self, artifacts: ArtifactService, *, clock: Callable[[], datetime] = _now) -> None:
        self.artifacts = artifacts
        self.clock = clock

    def create(
        self,
        task: TaskRecord,
        *,
        attempt_id: str,
        generation: int,
        worker_id: str,
        channel_id: str | None,
        plugin_state_ref: str,
        artifact_refs: list[str],
        next_global_action: str = "resume_plugin",
    ) -> GlobalCheckpoint:
        if not plugin_state_ref:
            raise CheckpointError("plugin_state_ref must not be empty")
        existing = self._next_revision(task, artifact_refs)
        root = _local_path(task.task.project.workspace_uri)
        if root is None:
            raise CheckpointError("checkpoint workspace must be locally accessible")
        checkpoint_dir = root / ".ai" / "checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_id = f"CP-{existing:04d}"
        values = {
            "schema_version": "1.0", "checkpoint_id": checkpoint_id,
            "revision": existing, "task_id": task.task.task_id,
            "attempt_id": attempt_id, "generation": generation,
            "plugin": task.task.plugin, "plugin_state_ref": plugin_state_ref,
            "global_status": "PAUSED", "worker_id": worker_id,
            "channel_id": channel_id, "artifact_refs": list(artifact_refs),
            "next_global_action": next_global_action,
            "created_at": self.clock().isoformat(),
        }
        # Hash the JSON representation that is actually written (Pydantic
        # normalizes UTC timestamps to ``Z``), avoiding a false mismatch after reload.
        provisional = GlobalCheckpoint.model_validate(values | {"payload_sha256": "0" * 64})
        digest = _digest(provisional.model_dump(mode="json"))
        checkpoint = provisional.model_copy(update={"payload_sha256": digest})
        target = checkpoint_dir / f"{checkpoint_id}.json"
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(_json(checkpoint), encoding="utf-8")
            temporary.replace(target)
            return self.artifacts.register(
                task.task.task_id, "checkpoint", str(target),
                attempt_id=attempt_id,
                sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                size_bytes=target.stat().st_size,
                latest_checkpoint=True,
            ) and checkpoint
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            raise CheckpointError("checkpoint persistence failed") from exc

    def load(self, task: TaskRecord, uri: str | None = None) -> GlobalCheckpoint:
        if not uri:
            uri = task.latest_checkpoint_uri
        if not uri:
            raise CheckpointError("task has no checkpoint")
        path = _local_path(uri)
        if path is None or not path.is_file():
            raise CheckpointError("checkpoint is missing or inaccessible")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            checkpoint = GlobalCheckpoint.model_validate(raw)
        except (OSError, ValueError) as exc:
            raise CheckpointError("checkpoint is invalid") from exc
        if checkpoint.task_id != task.task.task_id or checkpoint.plugin != task.task.plugin:
            raise CheckpointIncompatibleError("checkpoint task/plugin identity does not match")
        if checkpoint.schema_version != "1.0":
            raise CheckpointIncompatibleError("checkpoint schema version is incompatible")
        if task.current_attempt_id != checkpoint.attempt_id:
            raise CheckpointIncompatibleError("checkpoint attempt is no longer current")
        if checkpoint.global_status != "PAUSED":
            raise CheckpointIncompatibleError("checkpoint is not resumable")
        if _digest(raw | {"payload_sha256": None}) != checkpoint.payload_sha256:
            raise CheckpointError("checkpoint integrity hash mismatch")
        registered = {item.uri: item for item in self.artifacts.list_for_task(task.task.task_id)}
        record = registered.get(str(path))
        if record is None or record.sha256 != hashlib.sha256(path.read_bytes()).hexdigest():
            raise CheckpointError("checkpoint is not registered with its current hash")
        for ref in checkpoint.artifact_refs:
            artifact = registered.get(ref)
            ref_path = _local_path(ref)
            if artifact is None or ref_path is None or not ref_path.is_file():
                raise CheckpointError("checkpoint references a missing artifact")
            if artifact.sha256 and hashlib.sha256(ref_path.read_bytes()).hexdigest() != artifact.sha256:
                raise CheckpointError("checkpoint references a changed artifact")
        return checkpoint

    def accessible_artifact_refs(self, task_id: str) -> list[str]:
        """Return registered local refs that can be handed to another worker."""
        refs = []
        for artifact in self.artifacts.list_for_task(task_id):
            path = _local_path(artifact.uri)
            if path is not None and path.is_file():
                refs.append(artifact.uri)
        return refs

    def _next_revision(self, task: TaskRecord, artifact_refs: list[str]) -> int:
        revisions = []
        for item in self.artifacts.list_for_task(task.task.task_id):
            if item.artifact_type != "checkpoint":
                continue
            path = _local_path(item.uri)
            if path and path.is_file():
                try:
                    revisions.append(int(json.loads(path.read_text(encoding="utf-8")).get("revision", 0)))
                except (OSError, ValueError, TypeError):
                    continue
        return max(revisions, default=0) + 1


def _digest(values: dict) -> str:
    payload = dict(values)
    payload.pop("payload_sha256", None)
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _json(checkpoint: GlobalCheckpoint) -> str:
    return json.dumps(checkpoint.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
