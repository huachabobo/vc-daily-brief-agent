from datetime import timedelta

from vc_agent.domain import Item
from vc_agent.profile import (
    UserProfile,
    apply_profile_adjustments,
    item_allowed,
    resolve_digest_settings,
)
from vc_agent.utils.time import utcnow


def make_item(source_name: str = "NVIDIA", topic: str = "芯片", text: str = "chip launch benchmark"):
    now = utcnow() - timedelta(hours=2)
    return Item(
        item_id=1,
        raw_item_id=1,
        platform="youtube",
        source_key=source_name,
        source_name=source_name,
        platform_item_id="video-1",
        url="https://example.com/1",
        title=text,
        description=text,
        normalized_title=text,
        normalized_text=text,
        published_at=now,
        topic=topic,
        tags=[topic],
        seed_weight=1.0,
        score=1.0,
        summary="summary",
        why_it_matters="why",
    )


def test_profile_can_block_source_and_keyword():
    profile = UserProfile(blocked_sources=["NVIDIA"], blocked_keywords=["giveaway"])

    assert item_allowed(make_item(source_name="NVIDIA"), profile) is False
    assert item_allowed(make_item(source_name="Asianometry", text="chip giveaway"), profile) is False
    assert item_allowed(make_item(source_name="Asianometry"), profile) is True


def test_profile_adjustment_boosts_focus_topic_and_preferred_source():
    profile = UserProfile(focus_topics=["芯片"], preferred_sources=["NVIDIA"])
    item = make_item()

    updated = apply_profile_adjustments(item, profile)

    assert updated.score > 1.0
    assert "用户重点关注赛道" in updated.reasons
    assert "用户偏好来源" in updated.reasons


def test_profile_digest_overrides_defaults():
    profile = UserProfile(max_brief_items=8, exploration_slots=2)

    resolved = resolve_digest_settings(6, 1, profile)

    assert resolved == {"max_items": 8, "exploration_slots": 2}
