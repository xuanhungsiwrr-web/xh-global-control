"""Domain-plugin manifest and result contracts."""

from pydantic import Field, field_validator, model_validator

from xh_control.constants import ALLOWED_GLOBAL_LEARNING_FIELDS

from .base import ContractModel


class PluginManifest(ContractModel):
    plugin_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    interface_version: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    entrypoint_type: str = Field(min_length=1)
    entrypoint: str = Field(min_length=1)
    accepted_task_types: set[str] = Field(min_length=1)
    owns_domain_workflow: bool = True
    owns_domain_learning: bool = True
    required_global_capabilities: set[str] = Field(default_factory=set)
    allowed_global_learning_fields: set[str] = Field(
        default_factory=lambda: set(ALLOWED_GLOBAL_LEARNING_FIELDS)
    )

    @field_validator("owns_domain_workflow", "owns_domain_learning")
    @classmethod
    def plugin_must_own_domain_concerns(cls, value: bool) -> bool:
        if not value:
            raise ValueError("domain plugins must own their workflow and domain learning")
        return value

    @field_validator("allowed_global_learning_fields")
    @classmethod
    def learning_fields_must_be_operational(cls, value: set[str]) -> set[str]:
        forbidden = value - ALLOWED_GLOBAL_LEARNING_FIELDS
        if forbidden:
            names = ", ".join(sorted(forbidden))
            raise ValueError(f"non-operational global learning fields are forbidden: {names}")
        return value


class OutputArtifact(ContractModel):
    artifact_type: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    sha256: str | None = None


class ExecutionSummary(ContractModel):
    elapsed_seconds: float = Field(ge=0)
    api_spend_usd: float = Field(default=0, ge=0)
    subscription_calls: int = Field(default=0, ge=0)
    api_calls: int = Field(default=0, ge=0)
    retries: int = Field(default=0, ge=0)


class GlobalLearningSummary(ContractModel):
    model_performance: list[dict] = Field(default_factory=list)
    routing: list[dict] = Field(default_factory=list)
    provider_reliability: list[dict] = Field(default_factory=list)
    token_efficiency: list[dict] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def reject_domain_keys(cls, value: object) -> object:
        forbidden = {
            "engineering_rule", "legal_rule", "technical_rule", "technical_standard",
            "report_structure", "report_section_rule", "report_rule", "writing_rule",
            "chapter_rule", "construction_workflow_rule", "domain_knowledge", "domain_learning",
        }

        def inspect(item: object) -> None:
            if isinstance(item, dict):
                for key, child in item.items():
                    if isinstance(key, str) and key.lower() in forbidden:
                        raise ValueError("domain-specific keys are forbidden in global_learning")
                    inspect(child)
            elif isinstance(item, (list, tuple)):
                for child in item:
                    inspect(child)

        inspect(value)
        return value


class PluginResult(ContractModel):
    schema_version: str = "1.0"
    task_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    outputs: list[OutputArtifact] = Field(default_factory=list)
    execution_summary: ExecutionSummary
    global_learning: GlobalLearningSummary
    domain_learning_stored_by_plugin: bool = True
    domain_learning_candidate_count: int = Field(default=0, ge=0)
    handoff_uri: str | None = None
