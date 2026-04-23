from pathlib import Path

from fastapi.testclient import TestClient

from vc_agent.domain import Item
from vc_agent.feedback.processing import handle_feedback_payload
from vc_agent.feedback.server import create_app
from vc_agent.settings import Settings
from vc_agent.storage import Repository
from vc_agent.user_runtime import settings_for_user
from vc_agent.utils.time import utcnow


def test_feedback_callback_records_feedback_and_updates_state(tmp_path):
    root = Path(__file__).resolve().parents[1]
    settings = Settings.from_env(root)
    settings.db_path = tmp_path / "feedback.db"
    settings.ensure_runtime_dirs()

    repo = Repository(settings.db_path)
    repo.init_db()
    item = Item(
        item_id=None,
        raw_item_id=100,
        platform="youtube",
        source_key="source",
        source_name="High Signal Channel",
        platform_item_id="video-100",
        url="https://example.com/100",
        title="AI benchmark release",
        description="benchmark deployment signal",
        normalized_title="ai benchmark release",
        normalized_text="ai benchmark release benchmark deployment signal",
        published_at=utcnow(),
        topic="AI",
        tags=["AI"],
    )
    item_id = repo.upsert_item(item)

    client = TestClient(create_app(settings))
    response = client.post("/feishu/callback", json={"item_id": item_id, "label": "useful"})

    assert response.status_code == 200
    state = repo.load_preference_state()
    assert state.topic_weights["AI"] > 0


def test_feedback_handler_supports_card_action_payload_shape(tmp_path):
    root = Path(__file__).resolve().parents[1]
    settings = Settings.from_env(root)
    settings.db_path = tmp_path / "feedback_ws.db"
    settings.ensure_runtime_dirs()

    repo = Repository(settings.db_path)
    repo.init_db()
    item = Item(
        item_id=None,
        raw_item_id=101,
        platform="youtube",
        source_key="source",
        source_name="High Signal Channel",
        platform_item_id="video-101",
        url="https://example.com/101",
        title="Robot supply chain expansion",
        description="factory capacity update",
        normalized_title="robot supply chain expansion",
        normalized_text="robot supply chain expansion factory capacity update",
        published_at=utcnow(),
        topic="机器人",
        tags=["机器人"],
    )
    item_id = repo.upsert_item(item)

    result = handle_feedback_payload(
        repo,
        {
            "event": {
                "action": {
                    "value": {"item_id": str(item_id), "label": "dislike"},
                },
                "operator": {"open_id": "ou_test_feedback"},
            }
        },
        source_hint="feishu_long_connection",
    )

    assert result.label == "dislike"
    state = repo.load_preference_state()
    assert state.topic_weights["机器人"] < 0


def test_http_feedback_callback_uses_user_scoped_runtime_when_operator_exists(tmp_path):
    root = Path(__file__).resolve().parents[1]
    settings = Settings.from_env(root)
    settings.db_path = tmp_path / "global.db"
    settings.delivery_preferences_path = tmp_path / "delivery_preferences.json"
    settings.user_profile_config = tmp_path / "user_profile.yaml"
    settings.repo_root = tmp_path
    settings.ensure_runtime_dirs()

    global_repo = Repository(settings.db_path)
    global_repo.init_db()

    scoped_settings = settings_for_user(settings, "ou_http_user")
    scoped_repo = Repository(scoped_settings.db_path)
    scoped_repo.init_db()
    item = Item(
        item_id=None,
        raw_item_id=102,
        platform="youtube",
        source_key="source",
        source_name="High Signal Channel",
        platform_item_id="video-102",
        url="https://example.com/102",
        title="AI infra deal",
        description="infrastructure deployment signal",
        normalized_title="ai infra deal",
        normalized_text="ai infra deal infrastructure deployment signal",
        published_at=utcnow(),
        topic="AI",
        tags=["AI"],
    )
    item_id = scoped_repo.upsert_item(item)

    client = TestClient(create_app(settings))
    response = client.post(
        "/feishu/callback",
        json={
            "event": {
                "operator": {"open_id": "ou_http_user"},
                "action": {"value": {"item_id": str(item_id), "label": "useful"}},
            }
        },
    )

    assert response.status_code == 200
    assert scoped_repo.load_preference_state().topic_weights["AI"] > 0
    assert global_repo.load_preference_state().topic_weights == {}
