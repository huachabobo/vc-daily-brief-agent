from vc_agent.pipeline.run_once import load_sources


def test_load_sources_supports_multiple_platforms(tmp_path):
    config_path = tmp_path / "sources.yaml"
    config_path.write_text(
        """
sources:
  - name: "AI Explained"
    platform: "youtube"
    channel_id: "abc123"
    topics: ["AI"]
  - name: "TechCrunch AI"
    platform: "rss"
    feed_url: "https://example.com/feed"
    topics: ["AI"]
""".strip(),
        encoding="utf-8",
    )

    sources = load_sources(config_path)

    assert len(sources) == 2
    assert sources[0].platform == "youtube"
    assert sources[0].channel_id == "abc123"
    assert sources[1].platform == "rss"
    assert sources[1].feed_url == "https://example.com/feed"
