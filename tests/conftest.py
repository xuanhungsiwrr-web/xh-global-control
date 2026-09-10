"""Offline fixtures isolate all runtime writes in temporary directories."""

import shutil
import socket
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("M0 tests must remain offline")
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


@pytest.fixture
def config_root(tmp_path):
    source = Path(__file__).resolve().parents[1] / "config"
    return shutil.copytree(source, tmp_path / "config")
