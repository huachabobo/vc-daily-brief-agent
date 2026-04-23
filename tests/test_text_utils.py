from vc_agent.utils.text import compact_sentence


def test_compact_sentence_prefers_sentence_boundary_before_hard_cut():
    text = (
        "机器人行业正在从单点硬件转向平台化机会。"
        "如果通用模型先在工厂落地，再扩展到医疗和酒店，就可能打开更大的市场空间。"
    )

    result = compact_sentence(text, limit=48)

    assert result == "机器人行业正在从单点硬件转向平台化机会。"
