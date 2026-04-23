from datetime import timedelta

from vc_agent.domain import Item, PreferenceState
from vc_agent.ranking.rules import score_item
from vc_agent.utils.time import utcnow


def build_item(title, description):
    now = utcnow() - timedelta(hours=4)
    return Item(
        item_id=1,
        raw_item_id=1,
        platform="youtube",
        source_key="source",
        source_name="source",
        platform_item_id="video-1",
        url="https://example.com/1",
        title=title,
        description=description,
        normalized_title=title.lower(),
        normalized_text="{0} {1}".format(title, description).lower(),
        published_at=now,
        topic="AI",
        tags=["AI"],
        seed_weight=1.0,
    )


def test_scoring_penalizes_spam_against_signal():
    preferences = PreferenceState()
    signal_item = build_item(
        "Agent benchmark release for enterprise deployment",
        "The company announced a new benchmark and enterprise deployment update.",
    )
    spam_item = build_item(
        "AI livestream giveaway course promo",
        "Subscribe now for our livestream course and promo discount.",
    )

    signal_score, _ = score_item(signal_item, preferences)
    spam_score, _ = score_item(spam_item, preferences)

    assert signal_score > spam_score
