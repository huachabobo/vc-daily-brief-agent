from __future__ import annotations

from typing import Dict, List, Tuple

from vc_agent.domain import Item, PreferenceState
from vc_agent.utils.text import dedupe_list
from vc_agent.utils.time import utcnow


TOPIC_KEYWORDS = {
    "AI": ["ai", "agent", "llm", "model", "inference", "reasoning", "openai", "anthropic", "多模态", "模型", "推理", "智能体"],
    "芯片": ["chip", "gpu", "hbm", "semiconductor", "wafer", "packaging", "cuda", "asic", "芯片", "半导体", "封装", "算力", "先进制程"],
    "机器人": ["robot", "robotics", "humanoid", "embodied", "automation", "actuator", "具身", "机器人", "执行器", "自动化"],
}

TOPIC_SOURCE_HINTS = {
    "AI": ["openai", "anthropic", "ai explained"],
    "芯片": ["nvidia", "asianometry", "semiconductor", "intel", "tsmc"],
    "机器人": ["agility", "unitree", "figure", "boston dynamics", "robot"],
}

SIGNAL_WORDS = [
    "launch",
    "release",
    "benchmark",
    "funding",
    "series a",
    "series b",
    "customer",
    "deployment",
    "supply chain",
    "policy",
    "开源",
    "发布",
    "融资",
    "客户",
    "部署",
    "benchmark",
    "政策",
    "供应链",
    "量产",
]

SPAM_WORDS = [
    "giveaway",
    "subscribe",
    "livestream",
    "webinar",
    "course",
    "promo",
    "discount",
    "直播",
    "抽奖",
    "课程",
    "广告",
    "培训",
]


def classify_topic(text: str, preferred_topics: List[str]) -> str:
    weighted_hits = []
    lowered = text.lower()
    tokens = set(lowered.split())
    for topic, keywords in TOPIC_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            normalized_keyword = keyword.lower()
            if " " in normalized_keyword:
                if normalized_keyword in lowered:
                    score += 1
            elif normalized_keyword.isascii() and normalized_keyword.isalpha():
                if normalized_keyword in tokens:
                    score += 1
            else:
                if normalized_keyword in lowered:
                    score += 1
        if score:
            weighted_hits.append((topic, score))
    for preferred in preferred_topics:
        weighted_hits.append((preferred, 3))
    if not weighted_hits:
        return "其他"
    weighted_hits.sort(key=lambda item: item[1], reverse=True)
    return weighted_hits[0][0]


def infer_source_topic(source_name: str, preferred_topics: List[str]) -> str:
    lowered = source_name.lower()
    for topic, hints in TOPIC_SOURCE_HINTS.items():
        if any(hint in lowered for hint in hints):
            return topic
    return preferred_topics[0] if preferred_topics else "其他"


def suggest_tags(text: str, topic: str) -> List[str]:
    tags = [topic]
    lowered = text.lower()
    for keyword in SIGNAL_WORDS:
        if keyword.lower() in lowered:
            tags.append(keyword if len(keyword) <= 12 else keyword.title())
    return dedupe_list(tags[:6])


def score_item(item: Item, preferences: PreferenceState) -> Tuple[float, List[str]]:
    reasons = []
    score = 0.2

    if item.topic != "其他":
        score += 0.2
        reasons.append("命中核心赛道")
    else:
        score -= 0.08
        reasons.append("主题相关性偏弱")

    source_bonus = min(item.seed_weight * 0.18, 0.3)
    score += source_bonus
    reasons.append("来源权重 +{0:.2f}".format(source_bonus))

    text = "{0} {1}".format(item.title, item.description).lower()
    signal_hits = sum(1 for keyword in SIGNAL_WORDS if keyword.lower() in text)
    if signal_hits:
        signal_bonus = min(signal_hits * 0.09, 0.27)
        score += signal_bonus
        reasons.append("信号词 {0} 个".format(signal_hits))

    spam_hits = sum(1 for keyword in SPAM_WORDS if keyword.lower() in text)
    if spam_hits:
        spam_penalty = min(spam_hits * 0.18, 0.45)
        score -= spam_penalty
        reasons.append("噪音词 -{0:.2f}".format(spam_penalty))

    hours_old = max((utcnow() - item.published_at).total_seconds() / 3600, 0)
    if hours_old <= 24:
        score += 0.16
        reasons.append("24 小时内新内容")
    elif hours_old <= 72:
        score += 0.11
        reasons.append("72 小时内内容")
    elif hours_old <= 168:
        score += 0.05
        reasons.append("一周内内容")
    else:
        score -= 0.04
        reasons.append("时效性一般")

    source_pref = preferences.source_weights.get(item.source_name, 0.0)
    topic_pref = preferences.topic_weights.get(item.topic, 0.0)
    phrase_pref = 0.0
    for phrase, value in preferences.phrase_weights.items():
        if phrase and phrase in text:
            phrase_pref += value
    phrase_pref = max(min(phrase_pref, 0.2), -0.2)
    pref_total = max(min(source_pref + topic_pref + phrase_pref, 0.35), -0.35)
    if pref_total:
        score += pref_total
        reasons.append("反馈偏好修正 {0:+.2f}".format(pref_total))

    if len(item.description.strip()) < 40 and signal_hits == 0:
        score -= 0.08
        reasons.append("描述信息稀疏")

    return max(score, 0.0), reasons


def build_item(item: Item, preferences: PreferenceState) -> Item:
    item.score, item.reasons = score_item(item, preferences)
    return item
