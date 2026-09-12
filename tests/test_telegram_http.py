import logging
from threading import Event, Thread

from xh_control.interfaces.telegram_http import AsyncCommandDispatcher, handle_payload


def test_handle_payload_logs_full_controller_exception(caplog, monkeypatch):
    class FailingAdapter:
        async def handle_update(self, update):
            raise RuntimeError("synthetic /run failure")

    payload = {"update_id": "u-1", "user_id": "user-1", "chat_id": "chat-1", "text": "/run"}

    def run_immediate(coroutine):
        try:
            coroutine.send(None)
        except StopIteration as exc:
            return exc.value
        raise AssertionError("test coroutine unexpectedly suspended")

    monkeypatch.setattr("xh_control.interfaces.telegram_http.asyncio.run", run_immediate)
    with caplog.at_level(logging.ERROR, logger="xh_control.interfaces.telegram_http"):
        result = handle_payload(FailingAdapter(), payload)

    assert result == {"ok": False, "error": "Global Control command failed"}
    assert "Telegram command failed while handling payload" in caplog.text
    assert "RuntimeError: synthetic /run failure" in caplog.text


def test_dispatcher_keeps_concurrent_run_and_pause_on_one_event_loop():
    import asyncio

    class Adapter:
        def __init__(self):
            self.started = Event()
            self.release = None
            self.loop_ids = []

        async def handle_update(self, update):
            self.loop_ids.append(id(asyncio.get_running_loop()))
            if update.text == "/run":
                self.release = asyncio.Event()
                self.started.set()
                await self.release.wait()
                return "run stopped safely"
            assert self.release is not None
            self.release.set()
            return "paused"

    adapter = Adapter()
    dispatcher = AsyncCommandDispatcher()
    run_result = []
    thread = Thread(target=lambda: run_result.append(handle_payload(
        adapter,
        {"update_id": "1", "user_id": "u", "chat_id": "c", "text": "/run"},
        dispatcher,
    )))
    try:
        thread.start()
        assert adapter.started.wait(timeout=2)
        pause = handle_payload(
            adapter,
            {"update_id": "2", "user_id": "u", "chat_id": "c", "text": "/pause"},
            dispatcher,
        )
        thread.join(timeout=2)
    finally:
        dispatcher.close()

    assert pause == {"ok": True, "text": "paused"}
    assert run_result == [{"ok": True, "text": "run stopped safely"}]
    assert len(set(adapter.loop_ids)) == 1
