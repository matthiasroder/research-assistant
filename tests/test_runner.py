import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from research_platform.models import EvaluatedItem, ResearchBrief, ResearchItem, RunResult, Source
from research_platform.runner import load_source_brief, load_source_file, make_run_id, write_run


def _item(text: str = "Some text.") -> ResearchItem:
    return ResearchItem(
        id="item-1",
        source_id="source-1",
        source_type="webpage",
        title="A title",
        url="https://example.com",
        text=text,
    )


class MakeRunIdTests(unittest.TestCase):
    def test_no_trailing_hyphen_after_truncation(self):
        question = "Loop engineering for business AI work practices: extra words"
        run_id = make_run_id(question)
        self.assertFalse(run_id.endswith("-"))

    def test_slug_is_truncated(self):
        run_id = make_run_id("x" * 200)
        today = datetime.now().strftime("%Y-%m-%d")
        self.assertLessEqual(len(run_id), len(today) + 1 + 48)

    def test_empty_question_falls_back(self):
        self.assertTrue(make_run_id("???").endswith("research-run"))

    def test_collision_gets_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs_root = Path(tmp)
            base = make_run_id("same brief", runs_root=runs_root)
            (runs_root / base).mkdir()
            second = make_run_id("same brief", runs_root=runs_root)
            self.assertNotEqual(base, second)
            self.assertTrue(second.startswith(base))


class WriteRunTests(unittest.TestCase):
    def _result(self, text: str) -> RunResult:
        item = _item(text)
        return RunResult(
            run_id="2026-01-01-test",
            brief=ResearchBrief(question="test", mode="analyze-url"),
            sources=[Source.from_url("https://example.com")],
            items=[item],
            evaluated_items=[EvaluatedItem(item=item, relevance_score=3, summary="s")],
            findings_markdown="# Findings\n",
        )

    def test_item_text_is_excerpted_in_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            write_run(run_dir, self._result("x" * 2000), max_item_text_chars=100)
            items = json.loads((run_dir / "items.json").read_text())
            self.assertIn("truncated", items[0]["text"])
            self.assertLess(len(items[0]["text"]), 200)
            evaluated = json.loads((run_dir / "evaluated_items.json").read_text())
            self.assertIn("truncated", evaluated[0]["item"]["text"])

    def test_short_text_is_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            write_run(run_dir, self._result("short text"), max_item_text_chars=100)
            items = json.loads((run_dir / "items.json").read_text())
            self.assertEqual(items[0]["text"], "short text")

    def test_run_json_is_a_manifest_without_duplicated_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            write_run(run_dir, self._result("text"), max_item_text_chars=100)
            manifest = json.loads((run_dir / "run.json").read_text())
            self.assertEqual(manifest["counts"]["items"], 1)
            self.assertNotIn("items", manifest)
            self.assertNotIn("findings_markdown", manifest)
            for name in manifest["files"]:
                self.assertTrue((run_dir / name).exists())


class LoadSourceFileTests(unittest.TestCase):
    def test_loads_sources_with_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sources.yaml"
            path.write_text(
                "sources:\n"
                "  - id: feed-1\n"
                "    type: rss\n"
                "    name: Feed One\n"
                "    url: https://example.com/feed.xml\n"
            )
            sources = load_source_file(path)
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0].id, "feed-1")
            self.assertEqual(sources[0].access, {"method": "public"})

    def test_missing_file_returns_empty(self):
        self.assertEqual(load_source_file(Path("/nonexistent/sources.yaml")), [])


class LoadSourceBriefTests(unittest.TestCase):
    def test_reads_standing_brief(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sources.yaml"
            path.write_text("brief: >\n  Watch for agentic AI developments.\nsources: []\n")
            self.assertEqual(load_source_brief(path), "Watch for agentic AI developments.")

    def test_no_brief_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sources.yaml"
            path.write_text("sources: []\n")
            self.assertIsNone(load_source_brief(path))

    def test_blank_brief_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sources.yaml"
            path.write_text("brief: '  '\nsources: []\n")
            self.assertIsNone(load_source_brief(path))

    def test_missing_file_returns_none(self):
        self.assertIsNone(load_source_brief(Path("/nonexistent/sources.yaml")))
        self.assertIsNone(load_source_brief(None))


if __name__ == "__main__":
    unittest.main()
