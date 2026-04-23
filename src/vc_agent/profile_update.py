from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

from vc_agent.pipeline.run_once import load_sources
from vc_agent.profile import load_user_profile, merge_profile_patch, save_user_profile
from vc_agent.profile_nlp import PreferenceCompiler, render_patch_summary
from vc_agent.ranking.rules import TOPIC_KEYWORDS
from vc_agent.settings import Settings


def run_profile_update(repo_root: Path, argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="用自然语言更新 user_profile.yaml")
    parser.add_argument("--text", required=True, help="自然语言偏好描述")
    parser.add_argument("--dry-run", action="store_true", help="只展示 patch，不写入配置")
    parser.add_argument(
        "--profile-path",
        default=None,
        help="可选，自定义 user_profile.yaml 路径",
    )
    args = parser.parse_args(argv)

    settings = Settings.from_env(repo_root)
    profile_path = Path(args.profile_path) if args.profile_path else settings.user_profile_config
    current_profile = load_user_profile(profile_path)
    available_sources = [source.name for source in load_sources(settings.sources_config) if source.active]
    available_topics = list(TOPIC_KEYWORDS.keys())

    compiler = PreferenceCompiler(settings)
    compiled = compiler.compile(args.text, current_profile, available_topics, available_sources)
    updated_profile = merge_profile_patch(current_profile, compiled.patch)

    print(render_patch_summary(compiled))
    print("")
    print("更新后的 user_profile:")
    print(
        json.dumps(
            {
                "focus_topics": updated_profile.focus_topics,
                "blocked_topics": updated_profile.blocked_topics,
                "preferred_sources": updated_profile.preferred_sources,
                "preferred_keywords": updated_profile.preferred_keywords,
                "blocked_sources": updated_profile.blocked_sources,
                "blocked_keywords": updated_profile.blocked_keywords,
                "topic_weight_overrides": updated_profile.topic_weight_overrides,
                "source_weight_overrides": updated_profile.source_weight_overrides,
                "keyword_weight_overrides": updated_profile.keyword_weight_overrides,
                "digest": {
                    "max_items": updated_profile.max_brief_items,
                    "exploration_slots": updated_profile.exploration_slots,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if args.dry_run:
        print("")
        print("dry-run 模式，不写入文件。")
        return 0

    save_user_profile(profile_path, updated_profile)
    print("")
    print("已更新 {0}".format(profile_path))
    return 0
