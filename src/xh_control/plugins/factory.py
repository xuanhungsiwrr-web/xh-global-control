"""Bind registered plugin facades to their approved process transport."""

from .base import DomainPluginAdapter
from .process_adapter import ProcessPluginAdapter
from .xh_tuvan_adapter import XHTuvanAdapter


def bind_process_plugin(plugin_id: str, transport: ProcessPluginAdapter) -> DomainPluginAdapter:
    if plugin_id == "xh-tuvan":
        return XHTuvanAdapter(transport)
    return transport
