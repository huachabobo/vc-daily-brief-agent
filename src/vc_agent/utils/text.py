from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import List


STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "from",
    "into",
    "about",
    "today",
    "video",
    "podcast",
    "episode",
    "最新",
    "今天",
    "我们",
    "一个",
    "这个",
    "那个",
}


def normalize_text(value: str) -> str:
    lowered = value.lower()
    lowered = re.sub(r"https?://\S+", " ", lowered)
    lowered = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()


def compact_sentence(text: str, limit: int = 120) -> str:
    clean = re.sub(r"\s+", " ", text.strip())
    if len(clean) <= limit:
        return clean
    hard_limit = max(limit - 1, 1)
    prefix = clean[:hard_limit]

    # Prefer ending on a natural sentence boundary so generated brief text
    # reads like a polished user-facing note instead of a debug truncation.
    for boundary in ("。", "！", "？", ";", "；", ".", "!", "?"):
        position = prefix.rfind(boundary)
        if position >= min(max(int(limit * 0.3), 12), hard_limit - 1):
            return prefix[: position + 1].rstrip()

    for boundary in ("，", ",", "、", " "):
        position = prefix.rfind(boundary)
        if position >= int(limit * 0.7):
            return prefix[:position].rstrip() + "…"

    return prefix.rstrip() + "…"


def top_phrases(text: str, limit: int = 6) -> List[str]:
    tokens = [token for token in normalize_text(text).split(" ") if token and token not in STOPWORDS]
    seen = []
    for token in tokens:
        if len(token) <= 2:
            continue
        if token not in seen:
            seen.append(token)
        if len(seen) >= limit:
            break
    return seen


def dedupe_list(values: List[str]) -> List[str]:
    seen = set()
    ordered = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered
