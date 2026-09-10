from scripts.mock_telegram_gateway import normalize_update


def test_normalize_telegram_message():
    assert normalize_update({
        "update_id": 9,
        "message": {},
    }) is None
    update = {"update_id": 9, "message": {"message_id": 12, "chat": {"id": 600}, "from": {"id": 700}, "text": "/tasks"}}
    assert normalize_update(update) == {
        "update_id": "9", "user_id": "700", "chat_id": "600", "text": "/tasks"
    }


def test_normalize_ignores_non_text_messages():
    assert normalize_update({"message_id": 1, "chat": {"id": 1}, "from": {"id": 1}}) is None
