from xh_control.config import load_config
from xh_control.core import GlobalController, TaskService
from xh_control.interfaces.telegram import TelegramCommand, TelegramUpdate
from xh_control.state import TaskRepository, initialize_database


def run_immediate(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("test coroutine unexpectedly suspended")


def test_controller_creates_run_task_without_provider_logic(config_root):
    config = load_config(config_root)
    database = initialize_database(config)
    controller = GlobalController(config, task_service=TaskService(TaskRepository(database)))
    command = TelegramCommand(
        "run",
        options=(("plugin", "xh-tuvan"), ("project", "PROJECT"), ("task", "Assess readiness")),
    )

    response = run_immediate(controller.handle_telegram_command(command, TelegramUpdate("1", "u", "c", "")))

    assert response.startswith("Task:")
    records = controller.task_service.list_tasks()
    assert len(records) == 1
    assert records[0].task.plugin == "xh-tuvan"
    assert records[0].task.execution.master_preference.value == "AUTO"


def test_controller_preferences_are_scoped_to_telegram_user(config_root):
    config = load_config(config_root)
    database = initialize_database(config)
    controller = GlobalController(config, task_service=TaskService(TaskRepository(database)))
    user = TelegramUpdate("1", "u1", "c", "")

    run_immediate(controller.handle_telegram_command(TelegramCommand("master", ("claude",)), user))
    run_immediate(controller.handle_telegram_command(TelegramCommand("mode", ("economy",)), user))
    command = TelegramCommand("run", options=(("plugin", "xh-tuvan"), ("project", "P"), ("task", "T")))
    run_immediate(controller.handle_telegram_command(command, user))

    record = controller.task_service.list_tasks()[0]
    assert record.task.execution.master_preference.value == "CLAUDE"
    assert record.task.execution.cost_mode.value == "ECONOMY"


def test_pause_and_resume_do_not_fall_back_to_m5_stub(config_root):
    import pytest
    from xh_control.exceptions import TaskNotFoundError
    config = load_config(config_root)
    database = initialize_database(config)
    controller = GlobalController(config, task_service=TaskService(TaskRepository(database)))
    update = TelegramUpdate("1", "u", "c", "")

    with pytest.raises(TaskNotFoundError):
        run_immediate(controller.handle_telegram_command(TelegramCommand("pause", ("T-1",)), update))
    with pytest.raises(TaskNotFoundError):
        run_immediate(controller.handle_telegram_command(TelegramCommand("resume", ("T-1",)), update))
