"""Hermes-facing Telegram adapter.

Hermes is only the message gateway. Parsing, authorization, and dispatch stay
inside Global Control and are deliberately independent of Hermes internals.
"""

from __future__ import annotations

from dataclasses import dataclass
import shlex
from typing import Protocol


COMMANDS = frozenset({
    "run", "status", "tasks", "master", "mode", "cost", "pause",
    "resume", "stop", "approve", "deny",
})


class TelegramCommandError(ValueError):
    """A user-facing command syntax or authorization error."""


@dataclass(frozen=True, slots=True)
class TelegramUpdate:
    """Normalized message supplied by the gateway boundary."""

    update_id: str
    user_id: str
    chat_id: str
    text: str

    @classmethod
    def from_gateway_payload(cls, payload: dict) -> "TelegramUpdate":
        """Validate the small Hermes-to-Global message envelope."""
        if not isinstance(payload, dict):
            raise TelegramCommandError("Gateway payload must be an object")
        values = {key: payload.get(key) for key in ("update_id", "user_id", "chat_id", "text")}
        if any(not isinstance(value, (str, int)) or not str(value).strip() for value in values.values()):
            raise TelegramCommandError("Gateway payload requires update_id, user_id, chat_id, and text")
        return cls(*(str(values[key]) for key in ("update_id", "user_id", "chat_id", "text")))


@dataclass(frozen=True, slots=True)
class TelegramCommand:
    """Parsed command; no routing or domain policy is embedded here."""

    name: str
    positionals: tuple[str, ...] = ()
    options: tuple[tuple[str, str], ...] = ()

    def option(self, name: str, default: str | None = None) -> str | None:
        for key, value in self.options:
            if key == name:
                return value
        return default


def parse_command(text: str) -> TelegramCommand:
    """Parse one of the eleven MVP commands without executing it."""
    if not isinstance(text, str) or not text.strip():
        raise TelegramCommandError("Empty Telegram command")
    try:
        tokens = shlex.split(text.strip())
    except ValueError as exc:
        raise TelegramCommandError("Malformed quoting in command") from exc
    if not tokens or not tokens[0].startswith("/"):
        raise TelegramCommandError("Commands must start with '/'")
    head = tokens[0][1:].split("@", 1)[0].lower()
    if head not in COMMANDS:
        raise TelegramCommandError(f"Unsupported command: /{head}")
    positionals: list[str] = []
    options: list[tuple[str, str]] = []
    seen: set[str] = set()
    for token in tokens[1:]:
        if "=" in token:
            key, value = token.split("=", 1)
            key = key.lower()
            if not key or not value or key in seen:
                raise TelegramCommandError("Options must be non-empty and unique")
            seen.add(key)
            options.append((key, value))
        else:
            positionals.append(token)
    command = TelegramCommand(head, tuple(positionals), tuple(options))
    _validate_shape(command)
    return command


def _validate_shape(command: TelegramCommand) -> None:
    if command.name == "run":
        required = {key for key, _ in command.options}
        if not {"plugin", "project", "task"} <= required:
            raise TelegramCommandError("/run requires plugin=, project=, and task=")
        allowed = {"plugin", "project", "task", "workspace", "task_type", "report_type", "master", "mode", "permission"}
        if required - allowed:
            raise TelegramCommandError("/run contains an unsupported option")
        if command.positionals:
            raise TelegramCommandError("/run does not accept positional arguments")
        return
    if command.name in {"tasks", "cost"} and len(command.positionals) > 1:
        raise TelegramCommandError(f"/{command.name} accepts at most one task id")
    if command.name in {"status", "pause", "resume", "stop"} and len(command.positionals) != 1:
        raise TelegramCommandError(f"/{command.name} requires exactly one task id")
    if command.name in {"approve", "deny"} and len(command.positionals) != 1:
        raise TelegramCommandError(f"/{command.name} requires exactly one approval id")
    if command.name in {"master", "mode"} and len(command.positionals) != 1:
        raise TelegramCommandError(f"/{command.name} requires exactly one value")
    if command.name not in {"run", "tasks", "cost", "status", "pause", "resume", "stop", "approve", "deny", "master", "mode"}:
        raise TelegramCommandError("Unsupported command")
    if command.options:
        raise TelegramCommandError(f"/{command.name} does not accept options")


class TelegramController(Protocol):
    async def handle_telegram_command(
        self, command: TelegramCommand, update: TelegramUpdate
    ) -> str: ...


class TelegramAdapter:
    """Authorize and dispatch normalized gateway updates to Global Control."""

    def __init__(
        self,
        controller: TelegramController,
        *,
        allowed_user_ids: set[str] | frozenset[str],
        allowed_chat_ids: set[str] | frozenset[str] = frozenset(),
    ) -> None:
        self.controller = controller
        self.allowed_user_ids = frozenset(str(item) for item in allowed_user_ids)
        self.allowed_chat_ids = frozenset(str(item) for item in allowed_chat_ids)

    async def handle_update(self, update: TelegramUpdate) -> str:
        if not self._authorized(update):
            raise TelegramCommandError("Telegram user is not authorized")
        command = parse_command(update.text)
        return await self.controller.handle_telegram_command(command, update)

    def _authorized(self, update: TelegramUpdate) -> bool:
        return (
            str(update.user_id) in self.allowed_user_ids
            and (not self.allowed_chat_ids or str(update.chat_id) in self.allowed_chat_ids)
        )
