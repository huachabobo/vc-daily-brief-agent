from pathlib import Path

import yaml

from vc_agent.feedback.message_preferences import compose_update_reply, handle_preference_message
from vc_agent.profile import UserProfilePatch
from vc_agent.profile_nlp import CompiledPreference
from vc_agent.settings import Settings


def test_handle_preference_message_updates_profile_and_replies(tmp_path):
    root = tmp_path
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
    settings.openai_api_key = ""

    body = {
        "event": {
            "sender": {"sender_type": "user"},
            "message": {
                "chat_type": "p2p",
                "message_type": "text",
                "chat_id": "oc_test_chat",
                "content": '{"text":"更关注 AI 和机器人，优先 NVIDIA、SemiEngineering，少给我 benchmark，日报控制在 5 条"}',
            },
        }
    }

    result = handle_preference_message(settings, body)

    assert result.should_reply is True
    assert result.updated is True
    assert "已更新偏好" in result.reply_text

    saved = yaml.safe_load((root / "config" / "user_profile.yaml").read_text(encoding="utf-8"))
    assert "AI" in saved["focus_topics"]
    assert "NVIDIA" in saved["preferred_sources"]
    assert saved["digest"]["max_items"] == 5


def test_handle_preference_message_returns_help_for_non_preference_text(tmp_path):
    root = Path(tmp_path)
    (root / "config").mkdir()
    (root / "config" / "sources.yaml").write_text("sources: []\n", encoding="utf-8")
    (root / "config" / "user_profile.yaml").write_text("focus_topics: []\n", encoding="utf-8")
    settings = Settings.from_env(root)
    settings.sources_config = root / "config" / "sources.yaml"
    settings.user_profile_config = root / "config" / "user_profile.yaml"
    settings.openai_api_key = ""

    body = {
        "event": {
            "sender": {"sender_type": "user"},
            "message": {
                "chat_type": "p2p",
                "message_type": "text",
                "chat_id": "oc_test_chat",
                "content": '{"text":"你好"}',
            },
        }
    }

    result = handle_preference_message(settings, body)

    assert result.should_reply is True
    assert result.updated is False
    assert "自然语言更新偏好" in result.reply_text or "支持用自然语言更新偏好" in result.reply_text


def test_compose_update_reply_falls_back_without_openai(tmp_path):
    settings = Settings.from_env(Path(tmp_path))
    settings.openai_api_key = ""

    reply = compose_update_reply(
        settings,
        "更关注 AI",
        CompiledPreference(
            patch=UserProfilePatch(add_focus_topics=["AI"], max_brief_items=5, rationale="test"),
            mode="heuristic",
        ),
        type("Profile", (), {"preferred_sources": ["NVIDIA"]})(),
    )

    assert "已更新偏好" in reply
    assert "关注赛道: AI" in reply
