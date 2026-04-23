from __future__ import annotations

from collections import OrderedDict
from typing import Dict, List, Optional

from vc_agent.domain import BriefEntry, DailyBrief, Item
from vc_agent.utils.text import compact_sentence


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


def build_daily_brief(brief_date: str, items: List[Item], previous_items: Optional[List[Item]] = None) -> DailyBrief:
    grouped: Dict[str, List[BriefEntry]] = OrderedDict((topic, []) for topic in TOPIC_ORDER)
    sorted_items = sorted(items, key=lambda value: value.score, reverse=True)

    for item in sorted_items:
        topic = item.topic if item.topic in grouped else "其他"
        grouped[topic].append(
            BriefEntry(
                item_id=item.item_id or 0,
                source_key=item.source_key,
                platform_item_id=item.platform_item_id,
                title=item.title,
                summary=item.summary,
                why_it_matters=item.why_it_matters,
                why_selected=describe_selection_reason(item),
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

    shifts = build_shift_notes(sorted_items, previous_items or [])
    markdown = render_markdown(brief_date, highlights, shifts, grouped)
    return DailyBrief(
        brief_date=brief_date,
        highlights=highlights,
        shifts=shifts,
        grouped_entries=grouped,
        markdown=markdown,
    )


def render_markdown(
    brief_date: str,
    highlights: List[str],
    shifts: List[str],
    grouped_entries: Dict[str, List[BriefEntry]],
) -> str:
    lines = ["# VC Daily Brief | {0}".format(brief_date), ""]
    lines.append("## 今日 3 个重点")
    for index, highlight in enumerate(highlights, start=1):
        lines.append("{0}. {1}".format(index, highlight))
    lines.append("")
    lines.append("## 今日变化")
    for index, shift in enumerate(shifts, start=1):
        lines.append("{0}. {1}".format(index, shift))
    lines.append("")
    lines.append("---")
    lines.append("")

    for topic, entries in grouped_entries.items():
        lines.append("## {0}".format(topic))
        for index, entry in enumerate(entries, start=1):
            lines.append("### {0}. {1}".format(index, entry.title))
            lines.append("**摘要**：{0}".format(entry.summary))
            lines.append("**Why it matters**：{0}".format(entry.why_it_matters))
            lines.append("**Why selected**：{0}".format(entry.why_selected))
            lines.append("**来源**：[{0}]({1})".format(entry.source_name, entry.source_url))
            lines.append("**标签**：{0}".format(" / ".join(entry.tags)))
            lines.append("**反馈动作**：👍 有用 | 👎 不想看")
            lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def describe_selection_reason(item: Item) -> str:
    polished = []
    for reason in item.reasons:
        if reason.startswith("来源权重"):
            polished.append("来源可信")
        elif reason.startswith("信号词"):
            polished.append("出现关键行业信号")
        elif reason.startswith("24 小时内"):
            polished.append("信息足够新")
        elif reason.startswith("72 小时内"):
            polished.append("仍在近三天窗口")
        elif reason.startswith("反馈偏好修正"):
            polished.append("与历史反馈偏好一致")
        elif reason.startswith("命中核心赛道"):
            polished.append("命中核心赛道")
        elif reason.startswith("一周内内容"):
            polished.append("仍在一周观察窗口")
    if not polished:
        polished = ["综合得分靠前"]
    return compact_sentence("；".join(polished[:3]), limit=60)


def build_shift_notes(current_items: List[Item], previous_items: List[Item]) -> List[str]:
    current_topic_counts = _topic_counts(current_items)
    previous_topic_counts = _topic_counts(previous_items)
    current_sources = [item.source_name for item in current_items]
    previous_sources = {item.source_name for item in previous_items}
    notes: List[str] = []

    if previous_items:
        new_topics = [topic for topic, count in current_topic_counts.items() if count and previous_topic_counts.get(topic, 0) == 0]
        if new_topics:
            notes.append("新增 {0} 视角，说明观察面比上一期更宽。".format(" / ".join(new_topics[:2])))

        topic_deltas = []
        for topic, count in current_topic_counts.items():
            delta = count - previous_topic_counts.get(topic, 0)
            if delta > 0:
                topic_deltas.append((topic, delta))
        topic_deltas.sort(key=lambda item: item[1], reverse=True)
        if topic_deltas:
            topic, _ = topic_deltas[0]
            notes.append("{0} 内容占比上升，成为今天的主要信号方向。".format(topic))

        new_sources = [source for source in current_sources if source not in previous_sources]
        if new_sources:
            notes.append("新增来源 {0}，补充了不同于上一期的分析视角。".format(" / ".join(_dedupe_preserve_order(new_sources)[:2])))
    else:
        lead_topic = _top_topic(current_topic_counts)
        if lead_topic:
            notes.append("今天的主线集中在 {0}，适合优先扫这一组。".format(lead_topic))
        if len(set(current_sources)) >= 3:
            notes.append("来源覆盖 {0} 家，避免单一渠道主导判断。".format(len(set(current_sources))))
        fresh_count = sum(1 for item in current_items if any(reason.startswith("24 小时内") for reason in item.reasons))
        if fresh_count:
            notes.append("{0} 条内容来自 24 小时窗口内，时效性较强。".format(fresh_count))

    if not notes:
        notes.append("今天的选题延续上一期结构，没有出现明显偏移。")

    return notes[:3]


def _topic_counts(items: List[Item]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        counts[item.topic] = counts.get(item.topic, 0) + 1
    return counts


def _top_topic(counts: Dict[str, int]) -> Optional[str]:
    if not counts:
        return None
    return sorted(counts.items(), key=lambda item: item[1], reverse=True)[0][0]


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered
