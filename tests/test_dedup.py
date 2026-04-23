from datetime import timedelta

from vc_agent.domain import Item
from vc_agent.ranking.dedup import deduplicate
from vc_agent.utils.time import utcnow


def build_item(item_id, title, score):
    now = utcnow() - timedelta(hours=1)
    return Item(
        item_id=item_id,
        raw_item_id=item_id,
        platform="youtube",
        source_key="source",
        source_name="source",
        platform_item_id="video-{0}".format(item_id),
        url="https://example.com/{0}".format(item_id),
        title=title,
        description=title,
        normalized_title=title.lower(),
        normalized_text=title.lower(),
        published_at=now,
        topic="AI",
        tags=["AI"],
        seed_weight=1.0,
        score=score,
    )


def test_deduplicate_marks_similar_title_as_duplicate():
    winner = build_item(1, "OpenAI releases new reasoning model for agents", 1.1)
    duplicate = build_item(2, "OpenAI releases new reasoning model for agent", 0.9)

    items = deduplicate([duplicate, winner], threshold=0.9)

    duplicate_item = next(item for item in items if item.item_id == 2)
    assert duplicate_item.duplicate_of == winner.platform_item_id
