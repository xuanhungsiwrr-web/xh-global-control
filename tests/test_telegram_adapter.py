import pytest

from xh_control.interfaces.telegram import (
    TelegramAdapter,
    TelegramCommandError,
    TelegramUpdate,
    parse_command,
)


def run_immediate(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("test coroutine unexpectedly suspended")


def test_parse_run_supports_quoted_task_and_optional_controls():
    command = parse_command(
        '/run plugin=xh-tuvan project=KE task="Lập Báo cáo NCKT" '
        'master=claude mode=balanced'
    )

    assert command.name == "run"
    assert command.option("plugin") == "xh-tuvan"
    assert command.option("task") == "Lập Báo cáo NCKT"
    assert command.option("master") == "claude"


@pytest.mark.parametrize(
    "text",
    [
        "/status",
        "/run plugin=xh-tuvan project=KE",
        "/master",
        "/unknown value",
        "status T-1",
    ],
)
def test_invalid_command_shapes_are_rejected(text):
    with pytest.raises(TelegramCommandError):
        parse_command(text)


def test_all_m5_commands_parse():
    examples = {
        "/run plugin=xh-tuvan project=KE task=hello",
        "/status T-1", "/tasks", "/master auto", "/mode balanced",
        "/cost T-1", "/pause T-1", "/resume T-1", "/stop T-1",
        "/approve A-1", "/deny A-1",
    }
    assert {parse_command(item).name for item in examples} == {
        "run", "status", "tasks", "master", "mode", "cost", "pause",
        "resume", "stop", "approve", "deny",
    }


def test_adapter_authorizes_before_dispatch():
    class Controller:
        async def handle_telegram_command(self, command, update):
            return f"handled /{command.name}"

    adapter = TelegramAdapter(Controller(), allowed_user_ids={"u1"}, allowed_chat_ids={"c1"})
    update = TelegramUpdate("1", "u1", "c1", "/tasks")
    assert run_immediate(adapter.handle_update(update)) == "handled /tasks"
    with pytest.raises(TelegramCommandError, match="not authorized"):
        run_immediate(adapter.handle_update(TelegramUpdate("2", "u2", "c1", "/tasks")))


def test_gateway_payload_is_normalized_inside_global_control():
    update = TelegramUpdate.from_gateway_payload(
        {"update_id": 1, "user_id": "u1", "chat_id": 2, "text": "/tasks"}
    )
    assert update == TelegramUpdate("1", "u1", "2", "/tasks")
