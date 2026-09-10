"""Minimal local HTTP boundary for Hermes -> Global Control updates.

Hermes owns Telegram polling and delivery. This endpoint accepts only a
normalized update and delegates all command policy to ``TelegramAdapter``.
"""

from __future__ import annotations

import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from .telegram import TelegramAdapter, TelegramCommandError, TelegramUpdate


def handle_payload(adapter: TelegramAdapter, payload: dict) -> dict:
    """Process one normalized gateway payload and return a safe JSON response."""
    try:
        update = TelegramUpdate.from_gateway_payload(payload)
        text = asyncio.run(adapter.handle_update(update))
    except TelegramCommandError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception:
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
                response = {"ok": False, "error": "Invalid JSON payload"}
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
