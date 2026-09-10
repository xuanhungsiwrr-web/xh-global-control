"""Strict base model used by versioned control-plane contracts."""

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Reject undeclared fields so domain data cannot leak into Global models."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
