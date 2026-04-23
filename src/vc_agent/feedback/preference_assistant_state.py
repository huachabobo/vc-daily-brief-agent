from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from vc_agent.profile import UserProfile, UserProfilePatch, patch_from_payload, patch_to_payload, profile_from_payload, profile_to_payload


@dataclass
class PendingPreferenceUpdate:
    user_key: str
    user_text: str
    mode: str
    patch: UserProfilePatch


@dataclass
class PreferenceHistoryEntry:
    previous_profile: UserProfile
    user_text: str
    mode: str


class PreferenceAssistantStateStore:
    def __init__(self, path: Path):
        self.path = path

    def get_pending(self, user_key: str) -> Optional[PendingPreferenceUpdate]:
        state = self._load()
        payload = state.get("pending", {}).get(user_key)
        if not isinstance(payload, dict):
            return None
        return PendingPreferenceUpdate(
            user_key=user_key,
            user_text=str(payload.get("user_text") or ""),
            mode=str(payload.get("mode") or "heuristic"),
            patch=patch_from_payload(payload.get("patch") or {}),
        )

    def set_pending(self, pending: PendingPreferenceUpdate) -> None:
        state = self._load()
        state.setdefault("pending", {})[pending.user_key] = {
            "user_text": pending.user_text,
            "mode": pending.mode,
            "patch": patch_to_payload(pending.patch),
        }
        self._save(state)

    def clear_pending(self, user_key: str) -> None:
        state = self._load()
        if user_key in state.get("pending", {}):
            state["pending"].pop(user_key, None)
            self._save(state)

    def append_history(self, user_key: str, entry: PreferenceHistoryEntry, limit: int = 10) -> None:
        state = self._load()
        history = state.setdefault("history", {}).setdefault(user_key, [])
        history.append(
            {
                "previous_profile": profile_to_payload(entry.previous_profile),
                "user_text": entry.user_text,
                "mode": entry.mode,
            }
        )
        state["history"][user_key] = history[-limit:]
        self._save(state)

    def pop_history(self, user_key: str) -> Optional[PreferenceHistoryEntry]:
        state = self._load()
        history = state.setdefault("history", {}).setdefault(user_key, [])
        if not history:
            return None
        payload = history.pop()
        self._save(state)
        return PreferenceHistoryEntry(
            previous_profile=profile_from_payload(payload.get("previous_profile") or {}),
            user_text=str(payload.get("user_text") or ""),
            mode=str(payload.get("mode") or "heuristic"),
        )

    def _load(self) -> Dict[str, Dict[str, List[dict]]]:
        if not self.path.exists():
            return {"pending": {}, "history": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
