from datetime import timedelta

from vc_agent.briefing import build_daily_brief, select_brief_items
from vc_agent.domain import Item
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


def test_compose_brief_groups_topics_and_limits_items():
    items = [
        make_item(1, "AI", 1.1, "A"),
        make_item(2, "芯片", 1.0, "B"),
        make_item(3, "机器人", 0.95, "C"),
        make_item(4, "AI", 0.8, "D"),
    ]

    selected = select_brief_items(items, max_items=3, min_score_threshold=0.5, exploration_slots=1)
    assert len(selected) == 3

    brief = build_daily_brief("2026-04-23", selected)
    assert "## AI" in brief.markdown
    assert "## 芯片" in brief.markdown
    assert "## 机器人" in brief.markdown
    assert "## 今日变化" in brief.markdown
    assert "**Why selected**" in brief.markdown
    assert len(brief.highlights) == 3


def test_compose_brief_can_compare_against_previous_items():
    current = [
        make_item(1, "芯片", 1.1, "Asianometry"),
        make_item(2, "机器人", 0.95, "Agility"),
    ]
    previous = [
        make_item(3, "AI", 0.9, "AI Explained"),
    ]

    brief = build_daily_brief("2026-04-23", current, previous_items=previous)

    assert any("新增" in shift or "占比上升" in shift for shift in brief.shifts)
