from pathlib import Path

from vc_agent.delivery_preferences import load_delivery_preferences
from vc_agent.feedback.intent_agent import handle_message_with_intent_agent
from vc_agent.settings import Settings


def _setup_repo(root: Path) -> Settings:
    (root / "config").mkdir()
    (root / "config" / "sources.yaml").write_text(
        """
sources:
  - name: "NVIDIA"
    platform: "youtube"
    channel_id: "abc123"
    topics: ["AI", "芯片"]
    active: true
  - name: "SemiEngineering"
    platform: "rss"
    feed_url: "https://example.com/feed"
    topics: ["芯片"]
    active: true
""".strip(),
        encoding="utf-8",
    )
    (root / "config" / "user_profile.yaml").write_text(
        "focus_topics: []\nblocked_topics: []\npreferred_sources: []\nblocked_sources: []\nblocked_keywords: []\ndigest:\n  max_items: 6\n  exploration_slots: 1\n",
        encoding="utf-8",
    )
    settings = Settings.from_env(root)
    settings.sources_config = root / "config" / "sources.yaml"
    settings.user_profile_config = root / "config" / "user_profile.yaml"
    settings.delivery_preferences_path = root / "data" / "delivery_preferences.json"
    settings.openai_api_key = "test-key"
    return settings


def _make_body(text: str) -> dict:
    return {
        "event": {
            "sender": {
                "sender_type": "user",
                "sender_id": {"open_id": "ou_test_user"},
            },
            "message": {
                "chat_type": "p2p",
                "message_type": "text",
                "chat_id": "oc_test_chat",
                "content": '{"text":"%s"}' % text,
            },
        }
    }


def test_intent_agent_can_execute_schedule_and_preference(monkeypatch, tmp_path):
    settings = _setup_repo(Path(tmp_path))
    monkeypatch.setattr(
        "vc_agent.feedback.intent_agent._plan_tools",
        lambda settings, text: ["schedule", "preference"],
    )
    monkeypatch.setattr(
        "vc_agent.feedback.intent_agent._summarize_execution",
        lambda settings, user_text, notes: "我已经先改好了推送设置，也准备好了新的偏好预览。",
    )

    result = handle_message_with_intent_agent(settings, _make_body("改成 9 点推送，推送 5 条"))

    assert result.handled is True
    assert result.reply_card is not None
    assert any("推送设置" in text or "09:00" in text for text in result.reply_texts)
    preferences = load_delivery_preferences(settings.delivery_preferences_path, settings.timezone)
    assert preferences.daily_time == "09:00"


def test_intent_agent_can_trigger_generate_now(monkeypatch, tmp_path):
    settings = _setup_repo(Path(tmp_path))
    monkeypatch.setattr(
        "vc_agent.feedback.intent_agent._plan_tools",
        lambda settings, text: ["generate_now"],
    )

    result = handle_message_with_intent_agent(settings, _make_body("现在就帮我重新生成日报吧"))

    assert result.handled is True
    assert result.trigger_generate_now is True
    assert result.reply_card is None


def test_intent_agent_can_reply_to_general_chat(monkeypatch, tmp_path):
    settings = _setup_repo(Path(tmp_path))
    settings.openai_api_key = ""
    monkeypatch.setattr(
        "vc_agent.feedback.intent_agent._plan_tools",
        lambda settings, text: [],
    )

    result = handle_message_with_intent_agent(settings, _make_body("你好 你是什么 AI"))

    assert result.handled is True
    assert len(result.reply_texts) == 1
    assert "VC Daily Brief" in result.reply_texts[0] or "助手" in result.reply_texts[0]


def test_intent_agent_uses_heuristics_when_openai_is_unavailable(tmp_path):
    settings = _setup_repo(Path(tmp_path))
    settings.openai_api_key = ""

    result = handle_message_with_intent_agent(settings, _make_body("改成 9 点推送，推送 5 条"))

    assert result.handled is True
    assert result.reply_card is not None
    preferences = load_delivery_preferences(settings.delivery_preferences_path, settings.timezone)
    assert preferences.daily_time == "09:00"
