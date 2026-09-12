import logging

from xh_control.interfaces.telegram_http import handle_payload


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
