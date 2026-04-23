from datetime import timedelta

from vc_agent.domain import Item, PreferenceState
from vc_agent.ranking.learner import apply_feedback
from vc_agent.ranking.rules import score_item
from vc_agent.utils.time import utcnow


def make_item():
    now = utcnow() - timedelta(hours=3)
    return Item(
        item_id=1,
        raw_item_id=1,
        platform="youtube",
        source_key="source",
        source_name="NVIDIA",
        platform_item_id="video-1",
        url="https://example.com/1",
        title="HBM supply chain benchmark update",
        description="This video discusses HBM supply chain and deployment timing.",
        normalized_title="hbm supply chain benchmark update",
        normalized_text="hbm supply chain benchmark update deployment timing",
        published_at=now,
        topic="芯片",
        tags=["芯片"],
        seed_weight=1.0,
    )


def test_feedback_changes_next_round_score():
    item = make_item()
    state = PreferenceState()
    initial_score, _ = score_item(item, state)

    updated_state = apply_feedback(state, item, "useful")
    next_score, _ = score_item(item, updated_state)

    assert next_score > initial_score
