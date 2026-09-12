"""Minimal local HTTP boundary for Hermes -> Global Control updates.

Hermes owns Telegram polling and delivery. This endpoint accepts only a
normalized update and delegates all command policy to ``TelegramAdapter``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from typing import Callable

from .telegram import TelegramAdapter, TelegramCommandError, TelegramUpdate

logger = logging.getLogger(__name__)


class AsyncCommandDispatcher:
    """Run every controller coroutine on one long-lived event loop."""

    def __init__(self) -> None:
        self._ready = Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = Thread(target=self._run, name="xh-control-loop", daemon=True)
        self._thread.start()
        self._ready.wait()

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()
        self._loop.close()

    def run(self, coroutine):
        if self._loop is None:
            raise RuntimeError("command dispatcher is unavailable")
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop).result()

    def close(self) -> None:
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)


def handle_payload(
    adapter: TelegramAdapter,
    payload: dict,
    dispatcher: AsyncCommandDispatcher | None = None,
) -> dict:
    """Process one normalized gateway payload and return a safe JSON response."""
    try:
        update = TelegramUpdate.from_gateway_payload(payload)
        coroutine = adapter.handle_update(update)
        text = dispatcher.run(coroutine) if dispatcher is not None else asyncio.run(coroutine)
    except TelegramCommandError as exc:
        logger.warning("Telegram command rejected: %s", exc, exc_info=True)
        return {"ok": False, "error": str(exc)}
    except Exception:
        logger.exception("Telegram command failed while handling payload=%r", payload)
        return {"ok": False, "error": "Global Control command failed"}
    return {"ok": True, "text": text}


def make_handler(
    adapter: TelegramAdapter,
    dispatcher: AsyncCommandDispatcher | None = None,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib protocol name
            if self.path != "/v1/telegram/update":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                response = handle_payload(adapter, payload, dispatcher)
            except (ValueError, json.JSONDecodeError):
                logger.exception("Telegram HTTP request contained invalid JSON")
                response = {"ok": False, "error": "Invalid JSON payload"}
            except Exception:
                logger.exception("Telegram HTTP request failed before response")
                response = {"ok": False, "error": "Global Control command failed"}
            body = json.dumps(response, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:
            return

    return Handler


def serve(adapter: TelegramAdapter, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Run the loopback-only Hermes bridge until interrupted."""
    dispatcher = AsyncCommandDispatcher()
    server = ThreadingHTTPServer((host, port), make_handler(adapter, dispatcher))
    try:
        server.serve_forever()
    finally:
        server.server_close()
        dispatcher.close()
