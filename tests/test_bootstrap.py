from pathlib import Path

from vc_agent.bootstrap import env_key_order, parse_env_file, render_env


def test_parse_and_render_env_preserves_template_order(tmp_path):
    template = tmp_path / ".env.example"
    template.write_text(
        "YOUTUBE_API_KEY=\n"
        "\n"
        "OPENAI_API_KEY=\n"
        "OPENAI_BASE_URL=https://api.openai.com/v1\n"
        "\n"
        "DB_PATH=data/vc_agent.db\n",
        encoding="utf-8",
    )
    env_file = tmp_path / ".env"
    env_file.write_text(
        "YOUTUBE_API_KEY=yt-key\n"
        "OPENAI_API_KEY=oa-key\n"
        "DB_PATH=data/custom.db\n",
        encoding="utf-8",
    )

    values = parse_env_file(env_file)
    keys = env_key_order(template)
    rendered = render_env(keys, values)

    assert values["YOUTUBE_API_KEY"] == "yt-key"
    assert keys == ["YOUTUBE_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "DB_PATH"]
    assert rendered == (
        "YOUTUBE_API_KEY=yt-key\n"
        "\n"
        "OPENAI_API_KEY=oa-key\n"
        "OPENAI_BASE_URL=\n"
        "\n"
        "DB_PATH=data/custom.db\n"
    )
