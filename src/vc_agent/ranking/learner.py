from __future__ import annotations

from typing import Dict

from vc_agent.domain import Item, PreferenceState
from vc_agent.utils.text import top_phrases


def _adjust(mapping: Dict[str, float], key: str, delta: float, lower: float = -1.0, upper: float = 1.0) -> None:
    mapping[key] = max(min(mapping.get(key, 0.0) + delta, upper), lower)


def apply_feedback(state: PreferenceState, item: Item, label: str) -> PreferenceState:
    delta = 0.12 if label == "useful" else -0.18
    _adjust(state.source_weights, item.source_name, delta)
    _adjust(state.topic_weights, item.topic, delta / 2)

    phrase_delta = 0.05 if label == "useful" else -0.08
    for phrase in top_phrases("{0} {1}".format(item.title, item.description), limit=6):
        _adjust(state.phrase_weights, phrase, phrase_delta, lower=-0.6, upper=0.6)

    return state
