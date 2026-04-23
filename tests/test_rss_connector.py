from vc_agent.connectors.rss import RSSConnector
from vc_agent.domain import SourceConfig


RSS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://example.com/feed</link>
    <item>
      <guid>entry-1</guid>
      <title>Chip benchmark update</title>
      <link>https://example.com/chip</link>
      <description><![CDATA[<p>New packaging benchmark with customer signal.</p>]]></description>
      <pubDate>Tue, 22 Apr 2026 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, content):
        self.content = content

    def get(self, *_args, **_kwargs):
        return FakeResponse(self.content)


def test_rss_connector_parses_entries_and_strips_html():
    connector = RSSConnector(max_fetch_per_source=5)
    connector.session = FakeSession(RSS_XML)

    items = connector.fetch_since(
        [
            SourceConfig(
                name="SemiEngineering",
                platform="rss",
                feed_url="https://example.com/feed",
                topics=["芯片"],
            )
        ],
        "2026-04-20T00:00:00+00:00",
    )

    assert len(items) == 1
    assert items[0].platform == "rss"
    assert items[0].source_name == "SemiEngineering"
    assert items[0].url == "https://example.com/chip"
    assert items[0].description == "New packaging benchmark with customer signal."
