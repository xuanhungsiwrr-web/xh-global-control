import importlib.util
import json
from pathlib import Path

import pytest


PLUGIN_PATH = Path(__file__).parents[1] / "integrations" / "hermes_global_control" / "__init__.py"
SPEC = importlib.util.spec_from_file_location("hermes_global_control", PLUGIN_PATH)
assert SPEC and SPEC.loader
plugin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plugin)


def test_registers_only_telegram_platform_handler():
    calls = []

    class Context:
        def register_platform_handler(self, platform, factory):
            calls.append((platform, factory))

    plugin.register(Context())

    assert calls == [("telegram", plugin._wire_telegram)]


def test_wires_scoped_commands_ahead_of_hermes(monkeypatch):
    handlers = []

    class CommandHandler:
        def __init__(self, command, callback):
            self.command = command
            self.callback = callback

    import sys
    import types
    telegram = types.ModuleType("telegram")
    telegram_ext = types.ModuleType("telegram.ext")
    telegram_ext.CommandHandler = CommandHandler
    monkeypatch.setitem(sys.modules, "telegram", telegram)
    monkeypatch.setitem(sys.modules, "telegram.ext", telegram_ext)

    class Application:
        def add_handler(self, handler, group=0):
            handlers.append((handler.command, handler.callback, group))

    plugin._wire_telegram(Application(), object())

    assert [item[0] for item in handlers] == list(plugin.CONTROL_COMMANDS)
    assert all(item[1] is plugin._handle_telegram and item[2] == -100 for item in handlers)


def test_forward_normalized_payload_once(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"ok": true, "text": "Queued: T-1"}'

    class Opener:
        calls = []

        def open(self, request, *, timeout):
            self.calls.append((request, timeout))
            return Response()

    opener = Opener()
    monkeypatch.setattr(plugin, "build_opener", lambda *_args: opener)
    payload = {"update_id": "1", "user_id": "2", "chat_id": "3", "text": "/tasks"}
    assert plugin._forward(payload) == "Queued: T-1"

    assert len(opener.calls) == 1
    request, timeout = opener.calls[0]
    assert request.full_url == plugin.DEFAULT_CONTROL_URL
    assert request.method == "POST"
    assert json.loads(request.data) == payload
    assert timeout == 15.0


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8765/v1/telegram/update",
        "http://example.com/v1/telegram/update",
        "http://127.0.0.1:8765/other",
    ],
)
def test_rejects_non_loopback_control_urls(monkeypatch, url):
    monkeypatch.setenv(plugin.CONTROL_URL_ENV, url)
    with pytest.raises(plugin.GlobalControlGatewayError, match="loopback"):
        plugin._control_url()


def test_global_error_is_preserved_without_retry(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"ok": false, "error": "Telegram user is not authorized"}'

    class Opener:
        calls = 0

        def open(self, *_args, **_kwargs):
            self.calls += 1
            return Response()

    opener = Opener()
    monkeypatch.setattr(plugin, "build_opener", lambda *_args: opener)
    with pytest.raises(plugin.GlobalControlGatewayError, match="not authorized"):
        plugin._forward({"update_id": "1", "user_id": "2", "chat_id": "3", "text": "/run"})
    assert opener.calls == 1
