from datetime import datetime, timezone
from pathlib import Path

import vc_agent.pipeline.run_once as run_once_module
from vc_agent.delivery.feishu import DeliveryResult
from vc_agent.domain import DailyBrief, Item, PreferenceState, SourceConfig
from vc_agent.profile import UserProfile
from vc_agent.settings import Settings


class _FakeRepository:
    def __init__(self, item: Item):
        self.item = item

    def init_db(self) -> None:
        return None

    def upsert_raw_item(self, raw_item) -> int:
        return 1

    def upsert_item(self, item: Item) -> int:
        return item.item_id or 1

    def list_items_since(self, since_iso: str):
        return [self.item]

    def load_preference_state(self) -> PreferenceState:
        return PreferenceState()

    def get_latest_brief_before(self, brief_date: str):
        return None

    def get_items_by_ids(self, item_ids):
        return []

    def save_brief(self, **kwargs) -> None:
        raise RuntimeError("sqlite is temporarily unavailable")


class _FakeSummaryClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def summarize(self, item: Item):
        return "一句摘要", "一句影响", ["AI"]


class _FakeNotifier:
    def __init__(self, settings: Settings):
        self.settings = settings

    def send(self, brief: DailyBrief) -> DeliveryResult:
        return DeliveryResult(channel="app:chat_id", status="sent", message_id="om_test_message")


class _FakeRawItem:
    source_key = "SemiEngineering"


def test_run_once_does_not_raise_when_brief_persistence_fails_after_send(monkeypatch, tmp_path):
    root = Path(tmp_path)
    settings = Settings.from_env(root)
    settings.output_dir = root / "sample_output"
    item = Item(
        item_id=1,
        raw_item_id=1,
        platform="rss",
        source_key="semi",
        source_name="SemiEngineering",
        platform_item_id="item-1",
        url="https://example.com/item-1",
        title="Test item",
        description="A useful signal",
        normalized_title="test item",
        normalized_text="test item useful signal",
        published_at=datetime(2026, 4, 23, 8, 0, tzinfo=timezone.utc),
        topic="AI",
        tags=["AI"],
        score=1.2,
    )
    fake_repo = _FakeRepository(item)

    monkeypatch.setattr(run_once_module, "Repository", lambda db_path: fake_repo)
    monkeypatch.setattr(run_once_module, "load_sources", lambda path: [SourceConfig(name="SemiEngineering", platform="rss", active=True)])
    monkeypatch.setattr(run_once_module, "load_user_profile", lambda path: UserProfile())
    monkeypatch.setattr(run_once_module, "build_connectors", lambda settings: {})
    monkeypatch.setattr(run_once_module, "fetch_raw_items", lambda connectors, sources, since_iso: [_FakeRawItem()])
    monkeypatch.setattr(run_once_module, "normalize_raw_item", lambda raw_item_id, raw_item, source_config=None: item)
    monkeypatch.setattr(run_once_module, "item_allowed", lambda item, profile: True)
    monkeypatch.setattr(run_once_module, "build_item", lambda item, preferences: item)
    monkeypatch.setattr(run_once_module, "apply_profile_adjustments", lambda item, profile: item)
    monkeypatch.setattr(run_once_module, "resolve_digest_settings", lambda **kwargs: {"max_items": 6, "exploration_slots": 1})
    monkeypatch.setattr(run_once_module, "deduplicate", lambda items: items)
    monkeypatch.setattr(run_once_module, "select_brief_items", lambda items, **kwargs: items)
    monkeypatch.setattr(run_once_module, "SummaryClient", _FakeSummaryClient)
    monkeypatch.setattr(
        run_once_module,
        "build_daily_brief",
        lambda brief_date, final_selected, previous_items=None: DailyBrief(
            brief_date=brief_date,
            highlights=["A highlight"],
            shifts=["A shift"],
            grouped_entries={"AI": []},
            markdown="# Brief",
        ),
    )
    monkeypatch.setattr(
        run_once_module,
        "write_brief",
        lambda output_dir, brief_date, content: output_dir / f"{brief_date}_brief.md",
    )
    monkeypatch.setattr(run_once_module, "FeishuNotifier", _FakeNotifier)

    result = run_once_module.run(settings)

    assert result["delivery_status"] == "sent"
    assert result["brief_saved"] is False
    assert result["delivery_channel"] == "app:chat_id"
