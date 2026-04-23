from datetime import timedelta

from vc_agent.briefing import select_brief_items
from vc_agent.domain import Item
from vc_agent.ranking.rules import classify_topic
from vc_agent.utils.time import utcnow


def make_item(item_id, topic, score, source_name):
    now = utcnow() - timedelta(hours=2)
    return Item(
        item_id=item_id,
        raw_item_id=item_id,
        platform="youtube",
        source_key=source_name,
        source_name=source_name,
        platform_item_id="video-{0}".format(item_id),
        url="https://example.com/{0}".format(item_id),
        title="title {0}".format(item_id),
        description="description {0}".format(item_id),
        normalized_title="title {0}".format(item_id),
        normalized_text="description {0}".format(item_id),
        published_at=now,
        topic=topic,
        tags=[topic],
        seed_weight=1.0,
        score=score,
        summary="summary",
        why_it_matters="why it matters",
    )


def test_classify_topic_does_not_treat_available_as_ai():
    text = "links available through newsletter and podcast"
    assert classify_topic(text, ["芯片"]) == "芯片"


def test_select_brief_items_preserves_topic_diversity():
    items = [
        make_item(1, "AI", 0.95, "NVIDIA"),
        make_item(2, "AI", 0.92, "NVIDIA"),
        make_item(3, "芯片", 0.70, "Asianometry"),
        make_item(4, "机器人", 0.68, "Agility"),
        make_item(5, "AI", 0.66, "OpenAI"),
    ]

    selected = select_brief_items(items, max_items=4, min_score_threshold=0.5, exploration_slots=1)
    topics = {item.topic for item in selected}

    assert "AI" in topics
    assert "芯片" in topics
    assert "机器人" in topics
