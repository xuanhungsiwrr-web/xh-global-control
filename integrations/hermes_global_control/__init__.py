"""Hermes gateway adapter for XH Global Control.

Hermes owns Telegram transport. This plugin intercepts only Global Control's
command set and forwards a small normalized envelope to the loopback control
API. Global Control remains responsible for authorization, parsing, policy,
routing, and durable state.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

logger = logging.getLogger(__name__)

DEFAULT_CONTROL_URL = "http://127.0.0.1:8765/v1/telegram/update"
CONTROL_URL_ENV = "XH_GLOBAL_CONTROL_URL"
CONTROL_COMMANDS = ("run", "tasks", "pause", "resume")
MAX_REPLY_CHARS = 4000


class GlobalControlGatewayError(RuntimeError):
    """Safe, user-facing gateway failure."""


def _control_url() -> str:
    url = os.getenv(CONTROL_URL_ENV, DEFAULT_CONTROL_URL).strip()
    parsed = urlparse(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.path != "/v1/telegram/update"
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise GlobalControlGatewayError(
            f"{CONTROL_URL_ENV} must target the loopback /v1/telegram/update endpoint"
        )
    return url


def _forward(payload: dict[str, str], *, timeout: float | None = None) -> str:
    """Forward once; mutating commands are deliberately never auto-retried."""
    if timeout is None:
        command = payload.get("text", "").lstrip().split(maxsplit=1)[0].split("@", 1)[0].lower()
        timeout = 920.0 if command in {"/run", "/resume"} else 45.0 if command == "/pause" else 15.0
    request = Request(
        _control_url(),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        # Ignore host proxy settings for a loopback-only trust boundary.
        with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        logger.warning("Global Control loopback request failed: %s", type(exc).__name__)
        raise GlobalControlGatewayError(
            "Global Control chưa sẵn sàng. Hãy kiểm tra dịch vụ điều khiển cục bộ."
        ) from exc

    try:
        result = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GlobalControlGatewayError("Global Control trả về phản hồi không hợp lệ.") from exc
    if not isinstance(result, dict):
        raise GlobalControlGatewayError("Global Control trả về phản hồi không hợp lệ.")
    if result.get("ok") is not True:
        message = result.get("error")
        raise GlobalControlGatewayError(
            str(message) if isinstance(message, str) and message else "Lệnh Global Control bị từ chối."
        )
    text = result.get("text")
    if not isinstance(text, str) or not text:
        raise GlobalControlGatewayError("Global Control không trả về nội dung phản hồi.")
    return text


def _chunks(text: str) -> list[str]:
    return [text[index:index + MAX_REPLY_CHARS] for index in range(0, len(text), MAX_REPLY_CHARS)]


async def _handle_telegram(update: Any, _context: Any) -> None:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if message is None or user is None or chat is None or not message.text:
        return
    payload = {
        "update_id": str(update.update_id),
        "user_id": str(user.id),
        "chat_id": str(chat.id),
        "text": str(message.text),
    }
    try:
        reply = await asyncio.to_thread(_forward, payload)
    except GlobalControlGatewayError as exc:
        reply = str(exc)
    for part in _chunks(reply):
        await message.reply_text(part)


def _wire_telegram(application: Any, _adapter: Any) -> None:
    # Imported only when Telegram connects, as required by Hermes' plugin API.
    from telegram.ext import CommandHandler

    # Negative group plus exact command scoping gives Global's commands priority
    # over same-named Hermes session commands without swallowing unrelated input.
    for command in CONTROL_COMMANDS:
        application.add_handler(CommandHandler(command, _handle_telegram), group=-100)


def register(ctx: Any) -> None:
    ctx.register_platform_handler("telegram", _wire_telegram)
