import json
import unittest
from unittest import mock

from research_platform.connectors.api import ApiJsonConnector, _first_value, _items_at_path
from research_platform.connectors.web import _ReadableHtmlParser
from research_platform.discovery import source_type_for_url
from research_platform.models import Source


class ReadableHtmlParserTests(unittest.TestCase):
    HTML = """
    <html>
      <head>
        <title>Article Title</title>
        <link rel="alternate" type="application/rss+xml" href="/feed.xml">
      </head>
      <body>
        <nav>Home About Subscribe Sign in</nav>
        <header>Site chrome and menus</header>
        <article>
          <p>This is the real article content that should be extracted.</p>
        </article>
        <form><button>Subscribe for free</button></form>
        <footer>Copyright footer links</footer>
        <script>var tracking = true;</script>
      </body>
    </html>
    """

    def parse(self) -> _ReadableHtmlParser:
        parser = _ReadableHtmlParser()
        parser.feed(self.HTML)
        return parser

    def test_extracts_article_text(self):
        self.assertIn("real article content", self.parse().text)

    def test_skips_page_chrome(self):
        text = self.parse().text
        for chrome in ("Subscribe", "Sign in", "Site chrome", "Copyright footer", "tracking"):
            self.assertNotIn(chrome, text)

    def test_captures_title_and_feed_links(self):
        parser = self.parse()
        self.assertEqual(parser.title, "Article Title")
        self.assertEqual(parser.feed_links, ["/feed.xml"])


class SourceTypeForUrlTests(unittest.TestCase):
    def test_x_post(self):
        self.assertEqual(source_type_for_url("https://x.com/openai/status/123"), "x_post")
        self.assertEqual(source_type_for_url("https://twitter.com/openai/status/123"), "x_post")

    def test_x_profile(self):
        self.assertEqual(source_type_for_url("https://x.com/openai"), "x_profile")

    def test_rss(self):
        self.assertEqual(source_type_for_url("https://example.com/feed.xml"), "rss")
        self.assertEqual(source_type_for_url("https://example.com/blog/atom"), "rss")

    def test_webpage_default(self):
        self.assertEqual(source_type_for_url("https://example.com/about"), "webpage")

    def test_x_and_twitter_only_match_real_hosts(self):
        self.assertEqual(source_type_for_url("https://examplex.com/blog"), "webpage")
        self.assertEqual(source_type_for_url("https://notwitter.com/status/123"), "webpage")
        self.assertEqual(source_type_for_url("https://subdomain.x.com/openai"), "x_profile")


class ApiHelperTests(unittest.TestCase):
    def test_items_at_path(self):
        payload = {"data": {"articles": [{"title": "a"}]}}
        self.assertEqual(_items_at_path(payload, "data.articles"), [{"title": "a"}])
        self.assertEqual(_items_at_path(payload, None), payload)

    def test_first_value(self):
        record = {"headline": "H", "title": "T"}
        self.assertEqual(_first_value(record, ["title", "headline"]), "T")
        self.assertIsNone(_first_value(record, ["missing"]))


class ApiJsonConnectorTests(unittest.TestCase):
    class JsonResponse:
        headers = {"content-type": "application/json"}

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _size):
            return json.dumps(self.payload).encode("utf-8")

    def test_preserves_evaluation_text_beyond_storage_cap(self):
        text = "x" * 1200 + " agentic research platforms"
        source = Source(
            id="api",
            type="api_json",
            name="API",
            url="https://provider.example/search",
            access={"store_full_text": False},
            metadata={"items_path": "articles", "text_fields": ["description"]},
        )
        payload = {"articles": [{"title": "Long item", "url": "https://example.com/item", "description": text}]}

        with mock.patch("urllib.request.urlopen", return_value=self.JsonResponse(payload)):
            item = ApiJsonConnector().fetch(source, limit_items=1, limit_chars=2000)[0]

        self.assertIn("agentic research platforms", item.text)
        self.assertEqual(item.access_rights["max_store_chars"], 1000)


if __name__ == "__main__":
    unittest.main()
