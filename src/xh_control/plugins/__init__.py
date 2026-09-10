"""Domain-plugin contracts and registry."""

from .base import DomainPluginAdapter
from .registry import PluginRegistration, PluginRegistry
from .xh_tuvan_adapter import XHTuvanAdapter

__all__ = [
    "DomainPluginAdapter",
    "PluginRegistration",
    "PluginRegistry",
    "XHTuvanAdapter",
]
