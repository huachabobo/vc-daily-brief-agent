from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List

import yaml

from vc_agent.briefing import build_daily_brief, select_brief_items
from vc_agent.connectors.rss import RSSConnector
from vc_agent.connectors.youtube import YouTubeConnector
from vc_agent.delivery.feishu import FeishuNotifier
from vc_agent.domain import Item, SourceConfig
from vc_agent.llm.client import SummaryClient
from vc_agent.profile import (
    apply_profile_adjustments,
    item_allowed,
    load_user_profile,
    resolve_digest_settings,
)
from vc_agent.ranking.dedup import deduplicate
from vc_agent.ranking.rules import build_item, classify_topic, infer_source_topic, suggest_tags
from vc_agent.settings import Settings
from vc_agent.storage import Repository
from vc_agent.utils.text import normalize_text
from vc_agent.utils.time import hours_ago, to_local_date, utcnow


LOGGER = logging.getLogger(__name__)


def run(settings: Settings) -> Dict[str, object]:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    settings.ensure_runtime_dirs()
    repo = Repository(settings.db_path)
    repo.init_db()

    sources = load_sources(settings.sources_config)
    profile = load_user_profile(settings.user_profile_config)
    connectors = build_connectors(settings)

    primary_since = hours_ago(settings.lookback_hours)
    fallback_since = hours_ago(settings.fallback_lookback_hours)

    fetched_raw_items = fetch_raw_items(connectors, sources, primary_since.isoformat())
    used_fallback = False
    if not fetched_raw_items:
        LOGGER.info("主时间窗没有新内容，自动放宽 lookback 到 %s 小时。", settings.fallback_lookback_hours)
        fetched_raw_items = fetch_raw_items(connectors, sources, fallback_since.isoformat())
        used_fallback = True

    source_map = {source.name: source for source in sources}
    for raw_item in fetched_raw_items:
        raw_item_id = repo.upsert_raw_item(raw_item)
        item = normalize_raw_item(raw_item_id, raw_item, source_map.get(raw_item.source_key))
        repo.upsert_item(item)

    candidate_since = fallback_since if used_fallback else primary_since
    candidates = [item for item in repo.list_items_since(candidate_since.isoformat()) if item_allowed(item, profile)]
    if not candidates:
        raise RuntimeError("没有可用于生成简报的候选内容，请检查频道配置、用户画像过滤条件或 API 权限。")

    preferences = repo.load_preference_state()
    digest_settings = resolve_digest_settings(
        default_max_items=settings.max_brief_items,
        default_exploration_slots=settings.exploration_slots,
        profile=profile,
    )
    rescored: List[Item] = []
    for item in candidates:
        rescored.append(apply_profile_adjustments(build_item(item, preferences), profile))
    rescored = deduplicate(rescored)

    summarizer = SummaryClient(settings)
    selected = select_brief_items(
        rescored,
        max_items=digest_settings["max_items"],
        min_score_threshold=settings.min_score_threshold,
        exploration_slots=digest_settings["exploration_slots"],
    )
    selected_ids = {item.item_id for item in selected}

    for item in rescored:
        if item.duplicate_of is None and item.item_id in selected_ids:
            item.summary, item.why_it_matters, llm_tags = summarizer.summarize(item)
            item.tags = llm_tags or item.tags
            item.selected_for_brief = True
        else:
            item.selected_for_brief = False
        repo.upsert_item(item)

    brief_date = to_local_date(utcnow(), settings.timezone)
    final_selected = [item for item in rescored if item.item_id in selected_ids and item.duplicate_of is None]
    previous_brief = repo.get_latest_brief_before(brief_date)
    previous_items: List[Item] = []
    if previous_brief:
        _, previous_item_ids = previous_brief
        previous_items = repo.get_items_by_ids(previous_item_ids)
    brief = build_daily_brief(brief_date, final_selected, previous_items=previous_items)
    markdown_path = write_brief(settings.output_dir, brief_date, brief.markdown)

    notifier = FeishuNotifier(settings)
    delivery = notifier.send(brief)
    brief_saved = True
    try:
        repo.save_brief(
            brief_date=brief_date,
            markdown_path=str(markdown_path),
            item_ids=[item.item_id for item in final_selected if item.item_id is not None],
            sent_via=delivery.channel,
            sent_status=delivery.status,
            message_id=delivery.message_id,
        )
    except Exception:
        brief_saved = False
        LOGGER.exception("日报已经发送，但写入 briefs 表失败。为避免重复推送，这次不会把投递视为失败。")

    result = {
        "brief_date": brief_date,
        "markdown_path": str(markdown_path),
        "fetched_count": len(fetched_raw_items),
        "candidate_count": len(candidates),
        "selected_count": len(final_selected),
        "delivery_channel": delivery.channel,
        "delivery_status": delivery.status,
        "brief_saved": brief_saved,
        "used_fallback_lookback": used_fallback,
    }
    LOGGER.info("run completed: %s", result)
    return result


def load_sources(path: Path) -> List[SourceConfig]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = []
    for entry in payload.get("sources", []):
        platform = (entry.get("platform", "youtube") or "youtube").strip().lower()
        sources.append(
            SourceConfig(
                name=entry["name"],
                platform=platform,
                channel_id=entry.get("channel_id"),
                feed_url=entry.get("feed_url"),
                seed_weight=float(entry.get("seed_weight", 1.0)),
                topics=list(entry.get("topics", [])),
                active=bool(entry.get("active", True)),
            )
        )
    return sources


def build_connectors(settings: Settings):
    return {
        "youtube": YouTubeConnector(
            api_key=settings.youtube_api_key,
            max_fetch_per_source=settings.max_fetch_per_source,
        ),
        "rss": RSSConnector(max_fetch_per_source=settings.max_fetch_per_source),
    }


def fetch_raw_items(connectors, sources: List[SourceConfig], since_iso: str):
    active_sources = [source for source in sources if source.active]
    if not active_sources:
        raise ValueError("config/sources.yaml 中没有 active=true 的内容源。")

    sources_by_platform: Dict[str, List[SourceConfig]] = {}
    for source in active_sources:
        sources_by_platform.setdefault(source.platform, []).append(source)

    collected = []
    for platform, platform_sources in sources_by_platform.items():
        connector = connectors.get(platform)
        if connector is None:
            LOGGER.warning("跳过不支持的平台: %s", platform)
            continue
        collected.extend(connector.fetch_since(platform_sources, since_iso))
    return collected


def normalize_raw_item(raw_item_id: int, raw_item, source_config: SourceConfig = None) -> Item:
    text = "{0}\n{1}".format(raw_item.title, raw_item.description)
    normalized_text = normalize_text(text)
    preferred_topics = source_config.topics if source_config else []
    topic = classify_topic(normalized_text, preferred_topics)
    if topic == "其他" and source_config:
        topic = infer_source_topic(raw_item.source_name, preferred_topics)
    tags = suggest_tags(normalized_text, topic)
    return Item(
        item_id=None,
        raw_item_id=raw_item_id,
        platform=raw_item.platform,
        source_key=raw_item.source_key,
        source_name=raw_item.source_name,
        platform_item_id=raw_item.platform_item_id,
        url=raw_item.url,
        title=raw_item.title,
        description=raw_item.description,
        normalized_title=normalize_text(raw_item.title),
        normalized_text=normalized_text,
        published_at=raw_item.published_at,
        topic=topic,
        tags=tags,
        seed_weight=source_config.seed_weight if source_config else 1.0,
    )


def write_brief(output_dir: Path, brief_date: str, content: str) -> Path:
    output_path = output_dir / "{0}_brief.md".format(brief_date)
    output_path.write_text(content, encoding="utf-8")
    return output_path
