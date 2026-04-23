from pathlib import Path

from vc_agent.delivery_preferences import load_delivery_preferences
from vc_agent.feedback.schedule_commands import (
    handle_schedule_message,
    looks_like_generate_now_request,
    looks_like_preference_followup,
)
from vc_agent.settings import Settings


def _settings(tmp_path: Path) -> Settings:
    settings = Settings.from_env(tmp_path)
    settings.delivery_preferences_path = tmp_path / "data" / "delivery_preferences.json"
    return settings


def _make_body(text: str) -> dict:
    return {
        "event": {
            "sender": {"sender_type": "user"},
            "message": {
                "chat_type": "p2p",
                "message_type": "text",
                "chat_id": "oc_test_chat",
                "content": '{"text":"%s"}' % text,
            },
        }
    }


def test_schedule_message_updates_daily_time(tmp_path):
    settings = _settings(Path(tmp_path))

    result = handle_schedule_message(settings, _make_body("以后每天早上 8 点半推送日报"))

    assert result.handled is True
    assert "08:30" in result.reply_text
    preferences = load_delivery_preferences(settings.delivery_preferences_path, settings.timezone)
    assert preferences.enabled is True
    assert preferences.daily_time == "08:30"
    assert preferences.target_type == "chat_id"
    assert preferences.target_id == "oc_test_chat"


def test_schedule_message_understands_shorter_natural_language(tmp_path):
    settings = _settings(Path(tmp_path))

    result = handle_schedule_message(settings, _make_body("改成 9 点推送"))

    assert result.handled is True
    preferences = load_delivery_preferences(settings.delivery_preferences_path, settings.timezone)
    assert preferences.daily_time == "09:00"


def test_schedule_message_can_disable_push(tmp_path):
    settings = _settings(Path(tmp_path))
    handle_schedule_message(settings, _make_body("每天 9:15 推送日报"))

    result = handle_schedule_message(settings, _make_body("先暂停每日推送"))

    assert result.handled is True
    preferences = load_delivery_preferences(settings.delivery_preferences_path, settings.timezone)
    assert preferences.enabled is False


def test_schedule_message_can_show_current_plan(tmp_path):
    settings = _settings(Path(tmp_path))
    handle_schedule_message(settings, _make_body("每天晚上 6 点推送日报"))

    result = handle_schedule_message(settings, _make_body("查看当前推送时间"))

    assert result.handled is True
    assert "18:00" in result.reply_text


def test_generate_now_request_detection():
    assert looks_like_generate_now_request(_make_body("现在生成日报"))
    assert looks_like_generate_now_request(_make_body("现在就帮我重新生成日报吧"))
    assert not looks_like_generate_now_request(_make_body("查看当前偏好"))


def test_preference_followup_detection():
    assert looks_like_preference_followup("改成 9 点推送，推送 5 条")
    assert looks_like_preference_followup("每天 9 点推送，更关注芯片")
    assert not looks_like_preference_followup("每天 9 点推送日报")
