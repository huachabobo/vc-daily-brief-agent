from __future__ import annotations

from collections import OrderedDict
from typing import Dict, List

from vc_agent.domain import BriefEntry, DailyBrief, Item


TOPIC_ORDER = ["AI", "芯片", "机器人", "其他"]


def select_brief_items(items: List[Item], max_items: int, min_score_threshold: float, exploration_slots: int) -> List[Item]:
    deduped = [item for item in sorted(items, key=lambda value: value.score, reverse=True) if item.duplicate_of is None]
    reliable = [item for item in deduped if item.score >= min_score_threshold]
    if len(reliable) < max_items:
        reliable = deduped[: max(max_items * 2, max_items)]

    selected: List[Item] = []
    selected_ids = set()
    source_counts: Dict[str, int] = {}

    # Seed one representative item per core topic when available.
    for topic in TOPIC_ORDER[:-1]:
        topic_candidates = [item for item in reliable if item.topic == topic and item.item_id not in selected_ids]
        if not topic_candidates:
            continue
        chosen = topic_candidates[0]
        selected.append(chosen)
        if chosen.item_id is not None:
            selected_ids.add(chosen.item_id)
        source_counts[chosen.source_name] = source_counts.get(chosen.source_name, 0) + 1
        if len(selected) >= max_items:
            break

    for item in reliable:
        if len(selected) >= max_items:
            break
        if item.item_id in selected_ids:
            continue
        # Prefer source diversity so a single publisher does not dominate the whole brief.
        if source_counts.get(item.source_name, 0) >= 2:
            continue
        selected.append(item)
        if item.item_id is not None:
            selected_ids.add(item.item_id)
        source_counts[item.source_name] = source_counts.get(item.source_name, 0) + 1

    if len(selected) < max_items:
        for item in reliable:
            if len(selected) >= max_items:
                break
            if item.item_id in selected_ids:
                continue
            selected.append(item)
            if item.item_id is not None:
                selected_ids.add(item.item_id)

    selected = selected[:max_items]
    for item in selected:
        item.selected_for_brief = True
    return selected


def build_daily_brief(brief_date: str, items: List[Item]) -> DailyBrief:
    grouped: Dict[str, List[BriefEntry]] = OrderedDict((topic, []) for topic in TOPIC_ORDER)
    sorted_items = sorted(items, key=lambda value: value.score, reverse=True)

    for item in sorted_items:
        topic = item.topic if item.topic in grouped else "其他"
        grouped[topic].append(
            BriefEntry(
                item_id=item.item_id or 0,
                title=item.title,
                summary=item.summary,
                why_it_matters=item.why_it_matters,
                source_name=item.source_name,
                source_url=item.url,
                topic=topic,
                tags=item.tags,
                score=item.score,
            )
        )

    grouped = OrderedDict((key, value) for key, value in grouped.items() if value)

    highlights = []
    for item in sorted_items[:3]:
        highlights.append("{0}：{1}".format(item.topic, item.why_it_matters))

    markdown = render_markdown(brief_date, highlights, grouped)
    return DailyBrief(
        brief_date=brief_date,
        highlights=highlights,
        grouped_entries=grouped,
        markdown=markdown,
    )


def render_markdown(brief_date: str, highlights: List[str], grouped_entries: Dict[str, List[BriefEntry]]) -> str:
    lines = ["# VC Daily Brief | {0}".format(brief_date), ""]
    lines.append("## 今日 3 个重点")
    for index, highlight in enumerate(highlights, start=1):
        lines.append("{0}. {1}".format(index, highlight))
    lines.append("")
    lines.append("---")
    lines.append("")

    for topic, entries in grouped_entries.items():
        lines.append("## {0}".format(topic))
        for index, entry in enumerate(entries, start=1):
            lines.append("### {0}. {1}".format(index, entry.title))
            lines.append("**摘要**：{0}".format(entry.summary))
            lines.append("**Why it matters**：{0}".format(entry.why_it_matters))
            lines.append("**来源**：[{0}]({1})".format(entry.source_name, entry.source_url))
            lines.append("**标签**：{0}".format(" / ".join(entry.tags)))
            lines.append("**反馈**：👍 useful (`item_id={0}`) | 👎 dislike (`item_id={0}`)".format(entry.item_id))
            lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## 使用说明")
    lines.append("- 飞书卡片按钮会直接回调反馈服务。")
    lines.append("- 本地调试可以 `POST /feishu/callback`，body 只需带 `item_id` 和 `label`。")
    lines.append("")
    return "\n".join(lines)
