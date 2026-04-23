from pathlib import Path

from fastapi.testclient import TestClient

from vc_agent.domain import Item
from vc_agent.feedback.processing import handle_feedback_payload
from vc_agent.feedback.server import create_app
from vc_agent.settings import Settings
from vc_agent.storage import Repository
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
