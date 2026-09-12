"""Temporary Telegram long-polling gateway for Global Control M5 acceptance.

This replaceable test gateway owns Telegram Bot API transport only. It forwards
normalized messages to Global Control and sends Global's response text back to
the originating chat. The bot token is read from ``TELEGRAM_BOT_TOKEN`` and is
never printed, persisted, or included in error messages.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_GLOBAL_URL = "http://127.0.0.1:8765/v1/telegram/update"
logger = logging.getLogger("mock_telegram_gateway")


def _log_http_failure(operation: str, exc: BaseException) -> None:
    if isinstance(exc, HTTPError):
        try:
            response_body = exc.read().decode("utf-8", errors="replace")
        except OSError:
            response_body = "<unable to read HTTP error body>"
        logger.error(
            "%s HTTP failure: code=%s reason=%r body=%r",
            operation, exc.code, exc.reason, response_body,
            exc_info=True,
        )
    else:
        logger.error("%s exception: %s: %s", operation, type(exc).__name__, exc, exc_info=True)


def _telegram_call(token: str, method: str, payload: dict, timeout: float) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    logger.info("Telegram request: method=%s payload=%s", method, payload)
    request = Request(url, data=urlencode(payload).encode("utf-8"), method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        _log_http_failure(f"Telegram {method}", exc)
        raise RuntimeError(f"Telegram {method} failed") from exc
    if not isinstance(result, dict) or result.get("ok") is not True:
        logger.error("Telegram response rejected: method=%s response=%s", method, result)
        raise RuntimeError(f"Telegram {method} returned an invalid response")
    logger.info("Telegram response: method=%s response=%s", method, result)
    return result


def normalize_update(update: dict) -> dict | None:
    """Convert a Telegram update into the Global Control update envelope."""
    if not isinstance(update, dict):
        return None
    message = update.get("message", update)
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    user = message.get("from")
    text = message.get("text")
    if not isinstance(chat, dict) or not isinstance(user, dict) or not isinstance(text, str):
        return None
    # Telegram's update_id is the durable polling cursor. Keep a message-only
    # fallback so the helper remains convenient for focused unit tests.
    update_id = update.get("update_id", message.get("message_id"))
    chat_id = chat.get("id")
    user_id = user.get("id")
    if not isinstance(update_id, int) or not isinstance(chat_id, (int, str)) or not isinstance(user_id, (int, str)):
        return None
    return {
        "update_id": str(update_id),
        "user_id": str(user_id),
        "chat_id": str(chat_id),
        "text": text,
    }


def forward_update(update: dict, global_url: str, timeout: float) -> dict:
    body = json.dumps(update, ensure_ascii=False).encode("utf-8")
    logger.info("Global Control request: url=%s payload=%s", global_url, update)
    request = Request(global_url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        _log_http_failure("Global Control", exc)
        raise RuntimeError("Global Control endpoint failed") from exc
    if not isinstance(result, dict):
        logger.error("Global Control response rejected: response=%s", result)
        raise RuntimeError("Global Control returned an invalid response")
    logger.info("Global Control response: %s", result)
    return result


def run(token: str, global_url: str, poll_timeout: int, http_timeout: float) -> None:
    offset: int | None = None
    logger.info(
        "Gateway started: global_url=%s poll_timeout=%s http_timeout=%s",
        global_url, poll_timeout, http_timeout,
    )
    while True:
        payload = {"timeout": poll_timeout}
        if offset is not None:
            payload["offset"] = offset
        try:
            response = _telegram_call(token, "getUpdates", payload, http_timeout)
            for item in response.get("result", []):
                if not isinstance(item, dict):
                    continue
                logger.info("Telegram update received: %s", item)
                update_id = item.get("update_id")
                if isinstance(update_id, int):
                    offset = update_id + 1
                normalized = normalize_update(item)
                if normalized is None:
                    logger.warning("Telegram update ignored: could not normalize update=%s", item)
                    continue
                logger.info("Telegram update normalized: %s", normalized)
                result = forward_update(normalized, global_url, http_timeout)
                text = result.get("text") or result.get("error")
                logger.info("Global Control command result: %s", result)
                if isinstance(text, str) and text:
                    _telegram_call(token, "sendMessage", {"chat_id": normalized["chat_id"], "text": text}, http_timeout)
        except RuntimeError as exc:
            logger.error("Gateway iteration failed: %s: %s", type(exc).__name__, exc, exc_info=True)
            time.sleep(3)


def _load_token(env_file: Path) -> str:
    """Read only the Telegram token from Hermes' local env file."""
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except (OSError, UnicodeError):
        return ""
    return ""


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Temporary Telegram -> Global Control gateway")
    parser.add_argument("--global-url", default=DEFAULT_GLOBAL_URL)
    parser.add_argument("--poll-timeout", type=int, default=30)
    parser.add_argument("--http-timeout", type=float, default=40.0)
    parser.add_argument("--env-file", type=Path, default=Path(r"C:\Users\xuanh\AppData\Local\hermes\.env"))
    args = parser.parse_args()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or _load_token(args.env_file)
    if not token:
        parser.error("TELEGRAM_BOT_TOKEN is not set")
    if args.poll_timeout < 1 or args.poll_timeout > 50 or args.http_timeout <= 0:
        parser.error("invalid timeout")
    try:
        run(token, args.global_url, args.poll_timeout, args.http_timeout)
    except KeyboardInterrupt:
        print("gateway stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
