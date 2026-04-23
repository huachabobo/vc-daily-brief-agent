from vc_agent.profile import UserProfile
from vc_agent.profile_nlp import PreferenceCompiler
from vc_agent.settings import Settings


def test_preference_compiler_heuristics_extracts_preferences(tmp_path):
    settings = Settings.from_env(tmp_path)
    settings.openai_api_key = ""
    compiler = PreferenceCompiler(settings)

    compiled = compiler.compile(
        "我更关注 AI 和机器人，优先 NVIDIA、SemiEngineering，少给我 benchmark，日报控制在 5 条，保留 1 个探索位。",
        current_profile=UserProfile(),
        available_topics=["AI", "芯片", "机器人"],
        available_sources=["NVIDIA", "SemiEngineering", "The Robot Report"],
    )

    assert compiled.mode == "heuristic"
    assert "AI" in compiled.patch.add_focus_topics
    assert "机器人" in compiled.patch.add_focus_topics
    assert "NVIDIA" in compiled.patch.add_preferred_sources
    assert compiled.patch.keyword_weight_overrides["benchmark"] < 0
    assert compiled.patch.max_brief_items == 5
    assert compiled.patch.exploration_slots == 1
