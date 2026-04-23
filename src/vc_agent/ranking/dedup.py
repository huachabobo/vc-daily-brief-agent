from __future__ import annotations

from typing import List

from vc_agent.domain import Item
from vc_agent.utils.text import similarity


def deduplicate(items: List[Item], threshold: float = 0.9) -> List[Item]:
    winners: List[Item] = []
    sorted_items = sorted(items, key=lambda item: item.score, reverse=True)
    for item in sorted_items:
        duplicate_of = None
        for winner in winners:
            if item.platform_item_id == winner.platform_item_id:
                duplicate_of = winner.platform_item_id
                break
            if item.normalized_title and winner.normalized_title:
                if similarity(item.normalized_title, winner.normalized_title) >= threshold:
                    duplicate_of = winner.platform_item_id
                    break
        item.duplicate_of = duplicate_of
        if duplicate_of is None:
            winners.append(item)
    return sorted_items
