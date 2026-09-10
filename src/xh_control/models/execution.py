"""Execution-channel data contract."""

from pydantic import Field, model_validator

from .base import ContractModel
from .enums import ChannelClass, ChannelHealth


class ExecutionChannel(ContractModel):
    channel_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    surface: str = Field(min_length=1)
    model: str | None = None
    channel_class: ChannelClass
    billing_mode: str = Field(min_length=1)
    capabilities: set[str] = Field(min_length=1)
    enabled: bool = True
    priority: int = 100
    health: ChannelHealth = ChannelHealth.UNKNOWN
    estimated_input_usd_per_mtoken: float | None = Field(default=None, ge=0)
    estimated_output_usd_per_mtoken: float | None = Field(default=None, ge=0)
    supports_files: bool = False
    supports_terminal: bool = False
    supports_structured_output: bool = False
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def billing_mode_matches_channel_class(self) -> "ExecutionChannel":
        is_subscription_billing = self.billing_mode == "subscription"
        is_subscription_class = self.channel_class == ChannelClass.SUBSCRIPTION
        if is_subscription_billing != is_subscription_class:
            raise ValueError(
                "subscription billing_mode is valid only for subscription channels"
            )
        return self
