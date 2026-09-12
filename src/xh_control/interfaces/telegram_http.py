"""Minimal local HTTP boundary for Hermes -> Global Control updates.

Hermes owns Telegram polling and delivery. This endpoint accepts only a
normalized update and delegates all command policy to ``TelegramAdapter``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from .telegram import TelegramAdapter, TelegramCommandError, TelegramUpdate

logger = logging.getLogger(__name__)


def handle_payload(adapter: TelegramAdapter, payload: dict) -> dict:
    """Process one normalized gateway payload and return a safe JSON response."""
    try:
        update = TelegramUpdate.from_gateway_payload(payload)
        text = asyncio.run(adapter.handle_update(update))
    except TelegramCommandError as exc:
        logger.warning("Telegram command rejected: %s", exc, exc_info=True)
        return {"ok": False, "error": str(exc)}
    except Exception:
        logger.exception("Telegram command failed while handling payload=%r", payload)
        return {"ok": False, "error": "Global Control command failed"}
    return {"ok": True, "text": text}


def make_handler(adapter: TelegramAdapter) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib protocol name
            if self.path != "/v1/telegram/update":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                response = handle_payload(adapter, payload)
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
    ThreadingHTTPServer((host, port), make_handler(adapter)).serve_forever()
