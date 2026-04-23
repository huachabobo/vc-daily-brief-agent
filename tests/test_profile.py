from datetime import timedelta

from vc_agent.domain import Item
from vc_agent.profile import (
    UserProfile,
    apply_profile_adjustments,
    item_allowed,
    merge_profile_patch,
    resolve_digest_settings,
    save_user_profile,
    load_user_profile,
    UserProfilePatch,
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


def test_profile_adjustment_supports_freeform_preferred_keywords():
    profile = UserProfile(preferred_keywords=["customer validation", "供应链"])
    item = make_item(text="customer validation and 供应链 progress")

    updated = apply_profile_adjustments(item, profile)

    assert updated.score > 1.0
    assert "用户偏好关键词" in updated.reasons


def test_profile_adjustment_supports_explicit_weight_overrides():
    profile = UserProfile(
        topic_weight_overrides={"芯片": 0.12},
        source_weight_overrides={"NVIDIA": 0.15},
        keyword_weight_overrides={"benchmark": -0.08},
    )
    item = make_item()

    updated = apply_profile_adjustments(item, profile)

    assert updated.score > 1.0
    assert any("用户主题权重" in reason for reason in updated.reasons)
    assert any("用户来源权重" in reason for reason in updated.reasons)
    assert any("用户关键词权重" in reason for reason in updated.reasons)


def test_profile_digest_overrides_defaults():
    profile = UserProfile(max_brief_items=8, exploration_slots=2)

    resolved = resolve_digest_settings(6, 1, profile)

    assert resolved == {"max_items": 8, "exploration_slots": 2}


def test_merge_profile_patch_updates_lists_and_weights():
    profile = UserProfile(
        focus_topics=["AI"],
        preferred_sources=["NVIDIA"],
        preferred_keywords=["商业化落地"],
        keyword_weight_overrides={"benchmark": -0.08},
        max_brief_items=6,
        exploration_slots=1,
    )
    patch = UserProfilePatch(
        add_focus_topics=["机器人"],
        add_preferred_sources=["SemiEngineering"],
        add_preferred_keywords=["客户验证"],
        topic_weight_overrides={"机器人": 0.11},
        source_weight_overrides={"SemiEngineering": 0.12},
        keyword_weight_overrides={"academic": -0.1, "benchmark": 0.0},
        max_brief_items=5,
    )

    merged = merge_profile_patch(profile, patch)

    assert merged.focus_topics == ["AI", "机器人"]
    assert merged.preferred_sources == ["NVIDIA", "SemiEngineering"]
    assert merged.preferred_keywords == ["商业化落地", "客户验证"]
    assert merged.topic_weight_overrides["机器人"] == 0.11
    assert merged.source_weight_overrides["SemiEngineering"] == 0.12
    assert "benchmark" not in merged.keyword_weight_overrides
    assert merged.max_brief_items == 5


def test_save_and_load_profile_preserves_weight_overrides(tmp_path):
    path = tmp_path / "user_profile.yaml"
    profile = UserProfile(
        focus_topics=["AI"],
        preferred_keywords=["客户验证"],
        topic_weight_overrides={"AI": 0.09},
        source_weight_overrides={"NVIDIA": 0.12},
        keyword_weight_overrides={"benchmark": -0.08},
        max_brief_items=5,
        exploration_slots=1,
    )

    save_user_profile(path, profile)
    loaded = load_user_profile(path)

    assert loaded.focus_topics == ["AI"]
    assert loaded.preferred_keywords == ["客户验证"]
    assert loaded.topic_weight_overrides == {"AI": 0.09}
    assert loaded.source_weight_overrides == {"NVIDIA": 0.12}
    assert loaded.keyword_weight_overrides == {"benchmark": -0.08}
    assert loaded.max_brief_items == 5
