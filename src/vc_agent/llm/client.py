from __future__ import annotations

import json
import logging
from typing import Tuple

import requests

from vc_agent.domain import Item
from vc_agent.settings import Settings
from vc_agent.utils.text import compact_sentence, dedupe_list


LOGGER = logging.getLogger(__name__)


class SummaryClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.session = requests.Session()

    def summarize(self, item: Item) -> Tuple[str, str, list]:
        if not self.settings.has_openai:
            return self._fallback(item)
        try:
            return self._summarize_with_llm(item)
        except Exception as exc:
            LOGGER.warning("LLM 摘要失败，自动降级到抽取式摘要: %s", exc)
            return self._fallback(item)

    def _summarize_with_llm(self, item: Item) -> Tuple[str, str, list]:
        url = self.settings.openai_base_url.rstrip("/") + "/chat/completions"
        prompt = (
            "你是给 VC 合伙人写简报的编辑。请基于给定内容输出 JSON，字段为"
            ' summary, why_it_matters, tags。summary 必须是两句中文；'
            "why_it_matters 必须说明投资信号；tags 为 3-5 个短标签。"
        )
        content = {
            "title": item.title,
            "description": item.description,
            "source": item.source_name,
            "topic": item.topic,
            "score_reasons": item.reasons,
        }
        response = self.session.post(
            url,
            headers={
                "Authorization": "Bearer {0}".format(self.settings.openai_api_key),
                "Content-Type": "application/json",
            },
            json={
                "model": self.settings.openai_model,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(content, ensure_ascii=False)},
                ],
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        raw_content = payload["choices"][0]["message"]["content"]
        parsed = json.loads(raw_content)
        summary = compact_sentence(parsed.get("summary", "").strip(), limit=160)
        why = compact_sentence(parsed.get("why_it_matters", "").strip(), limit=120)
        tags = dedupe_list([str(tag) for tag in parsed.get("tags", []) if str(tag).strip()])[:5]
        if not summary or not why:
            raise ValueError("LLM 返回缺少必要字段")
        return summary, why, tags

    def _fallback(self, item: Item) -> Tuple[str, str, list]:
        description = item.description.strip()
        first = compact_sentence(description or item.title, 80)
        second = compact_sentence(
            "内容聚焦 {0}，来源为 {1}，适合快速判断是否值得深挖。".format(item.topic, item.source_name),
            80,
        )
        why = compact_sentence(
            "它包含可跟踪的行业信号，能帮助判断 {0} 赛道的产品、融资或供应链变化。".format(item.topic),
            80,
        )
        return "{0} {1}".format(first, second), why, item.tags[:5]
