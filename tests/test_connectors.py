import json
import unittest
import urllib.error
from unittest import mock

from research_platform.connectors.api import ApiJsonConnector, _first_value, _items_at_path
from research_platform.connectors.rss import RssConnector
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
        self.assertFalse(item.access_rights["allow_external_processing"])

    def test_record_ids_are_stable_when_provider_order_changes(self):
        source = Source(
            id="api",
            type="api_json",
            name="API",
            url="https://provider.example/search",
            metadata={"items_path": "articles", "id_fields": ["id"]},
        )
        first = {"articles": [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}]}
        second = {"articles": list(reversed(first["articles"]))}
        with mock.patch("urllib.request.urlopen", return_value=self.JsonResponse(first)):
            first_items = ApiJsonConnector().fetch(source)
        with mock.patch("urllib.request.urlopen", return_value=self.JsonResponse(second)):
            second_items = ApiJsonConnector().fetch(source)
        self.assertEqual(
            {item.title: item.id for item in first_items},
            {item.title: item.id for item in second_items},
        )


class RssConnectorTests(unittest.TestCase):
    class BytesResponse:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _size):
            return self.body

    SOURCE = Source(
        id="feed",
        type="rss",
        name="Feed",
        url="https://example.com/feed.xml",
    )

    def test_labels_rss_entry_content_basis(self):
        body = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Feed</title>
        <item><guid>one</guid><title>One</title><link>https://example.com/one</link>
        <description>Exact feed evidence for this item.</description></item></channel></rss>"""
        connector = RssConnector(opener=lambda *args, **kwargs: self.BytesResponse(body))
        items, outcome = connector.fetch_with_outcome(self.SOURCE)
        self.assertEqual(outcome.status, "succeeded")
        self.assertEqual(items[0].provenance["content_basis"], "rss_entry")
        self.assertEqual(items[0].provenance["linked_fetch_status"], "not_requested")
        self.assertEqual(items[0].metadata["content_basis"], "rss_entry")

    def test_valid_empty_feed_is_distinct(self):
        body = b'<?xml version="1.0"?><rss version="2.0"><channel><title>Empty</title></channel></rss>'
        connector = RssConnector(opener=lambda *args, **kwargs: self.BytesResponse(body))
        items, outcome = connector.fetch_with_outcome(self.SOURCE)
        self.assertEqual(items, [])
        self.assertEqual(outcome.status, "empty")
        self.assertEqual(outcome.outcome_code, "empty_source")

    def test_transient_fetch_retries_at_most_three_times(self):
        body = b'<?xml version="1.0"?><rss version="2.0"><channel><title>Empty</title></channel></rss>'
        opener = mock.Mock(
            side_effect=[TimeoutError("one"), TimeoutError("two"), self.BytesResponse(body)]
        )
        connector = RssConnector(opener=opener, sleeper=lambda _delay: None)
        _, outcome = connector.fetch_with_outcome(self.SOURCE)
        self.assertEqual(opener.call_count, 3)
        self.assertEqual(outcome.attempts, 3)

    def test_authentication_failure_is_not_retried(self):
        error = urllib.error.HTTPError(self.SOURCE.url, 401, "unauthorized", {}, None)
        opener = mock.Mock(side_effect=error)
        connector = RssConnector(opener=opener, sleeper=lambda _delay: None)
        _, outcome = connector.fetch_with_outcome(self.SOURCE)
        self.assertEqual(opener.call_count, 1)
        self.assertEqual(outcome.outcome_code, "authentication_failed")


if __name__ == "__main__":
    unittest.main()
