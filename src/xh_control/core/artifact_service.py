"""Registry for opaque artifact and checkpoint references."""

from collections.abc import Callable
from datetime import UTC, datetime

from xh_control.models import ArtifactRecord
from xh_control.state.repositories import ArtifactRepository

from .identifiers import new_artifact_id


def _now() -> datetime:
    return datetime.now(UTC)


class ArtifactService:
    def __init__(
        self,
        repository: ArtifactRepository,
        *,
        clock: Callable[[], datetime] = _now,
        artifact_id_factory: Callable[[], str] = new_artifact_id,
    ) -> None:
        self.repository = repository
        self.clock = clock
        self.artifact_id_factory = artifact_id_factory

    def register(
        self,
        task_id: str,
        artifact_type: str,
        uri: str,
        *,
        attempt_id: str | None = None,
        sha256: str | None = None,
        size_bytes: int | None = None,
        latest_checkpoint: bool = False,
        artifact_id: str | None = None,
    ) -> ArtifactRecord:
        artifact = ArtifactRecord(
            artifact_id=artifact_id or self.artifact_id_factory(),
            task_id=task_id,
            attempt_id=attempt_id,
            artifact_type=artifact_type,
            uri=uri,
            sha256=sha256,
            size_bytes=size_bytes,
            created_at=self.clock(),
        )
        return self.repository.register(artifact, latest_checkpoint=latest_checkpoint)

    def get(self, artifact_id: str) -> ArtifactRecord:
        return self.repository.get(artifact_id)

    def list_for_task(self, task_id: str) -> list[ArtifactRecord]:
        return self.repository.list_for_task(task_id)
