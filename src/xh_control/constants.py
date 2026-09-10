"""Shared constants for the M0 bootstrap."""

from pathlib import Path

EXPECTED_CONFIG_ROOTS: dict[str, str] = {
    "system.yaml": "system",
    "routing.yaml": "routing",
    "channels.yaml": "channels",
    "subscriptions.yaml": "subscriptions",
    "budgets.yaml": "budgets",
    "plugins.yaml": "plugins",
    "workers.yaml": "workers",
    "permissions.yaml": "permissions",
}

ALLOWED_GLOBAL_LEARNING_FIELDS = frozenset(
    {
        "model_performance",
        "cost",
        "latency",
        "routing",
        "provider_reliability",
        "token_efficiency",
    }
)

PACKAGE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]
DEFAULT_CONFIG_ROOT = REPOSITORY_ROOT / "config"

