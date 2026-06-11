from __future__ import annotations

import os
import unittest
from unittest import mock

from research_platform.model_gateway import ModelGateway
from research_platform.models import ResearchBrief, ResearchItem


def _item(text: str, provenance: dict | None = None, title: str = "Untitled item") -> ResearchItem:
    return ResearchItem(
        id="item-1",
        source_id="source-1",
        source_type="webpage",
        title=title,
        url="https://example.com",
        text=text,
        provenance=provenance or {},
    )


BRIEF = ResearchBrief(question="agentic research platforms for knowledge work", mode="analyze-url")


class LocalEvaluationTests(unittest.TestCase):
    def test_matching_terms_raise_score(self):
        gateway = ModelGateway()
        matching = gateway.evaluate(_item("This covers agentic research platforms in depth for knowledge work."), BRIEF)
        unrelated = gateway.evaluate(_item("A recipe collection of seasonal soups and stews to cook at home."), BRIEF)
        self.assertGreater(matching.relevance_score, unrelated.relevance_score)
        self.assertEqual(unrelated.relevance_score, 1)

    def test_summary_uses_leading_sentences(self):
        gateway = ModelGateway()
        text = "First sentence about agentic platforms. Second sentence with more detail. Third one here too."
        evaluated = gateway.evaluate(_item(text), BRIEF)
        self.assertTrue(evaluated.summary.startswith("First sentence"))

    def test_failed_fetch_items_skip_the_api(self):
        gateway = ModelGateway({"evaluation": {"provider": "anthropic"}})
        failed = _item("Fetch error: boom", provenance={"connector": "rss", "retrieval": "failed"})
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with mock.patch.object(ModelGateway, "_evaluate_with_anthropic") as api:
                evaluated = gateway.evaluate(failed, BRIEF)
        api.assert_not_called()
        self.assertEqual(evaluated.item.id, "item-1")

    def test_anthropic_failure_falls_back_locally(self):
        gateway = ModelGateway({"evaluation": {"provider": "anthropic"}})
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with mock.patch.object(ModelGateway, "_evaluate_with_anthropic", side_effect=RuntimeError("api down")):
                evaluated = gateway.evaluate(_item("agentic research platforms text"), BRIEF)
        self.assertIn("local fallback", evaluated.rationale)


class SynthesizeTests(unittest.TestCase):
    def _two_items(self, gateway: ModelGateway) -> list:
        return [
            gateway._evaluate_locally(_item("Agentic research platforms text one."), BRIEF),
            gateway._evaluate_locally(_item("Knowledge work automation text two."), BRIEF),
        ]

    def test_empty_input(self):
        gateway = ModelGateway()
        self.assertIn("No relevant items", gateway.synthesize([], BRIEF))

    def test_local_provider_has_no_synthesis_section(self):
        gateway = ModelGateway()
        findings = gateway.synthesize(self._two_items(gateway), BRIEF)
        self.assertNotIn("## Synthesis", findings)

    def test_anthropic_synthesis_section_appears_first(self):
        gateway = ModelGateway({"evaluation": {"provider": "anthropic"}})
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with mock.patch.object(
                ModelGateway, "_synthesize_with_anthropic", return_value="- Theme across items."
            ) as api:
                findings = gateway.synthesize(self._two_items(gateway), BRIEF)
        api.assert_called_once()
        self.assertIn("## Synthesis", findings)
        self.assertIn("- Theme across items.", findings)
        self.assertLess(findings.index("## Synthesis"), findings.index("## Relevant Items"))

    def test_single_item_skips_synthesis(self):
        gateway = ModelGateway({"evaluation": {"provider": "anthropic"}})
        item = gateway._evaluate_locally(_item("Agentic research platforms text."), BRIEF)
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with mock.patch.object(ModelGateway, "_synthesize_with_anthropic") as api:
                findings = gateway.synthesize([item], BRIEF)
        api.assert_not_called()
        self.assertNotIn("## Synthesis", findings)

    def test_synthesis_failure_degrades_to_listing(self):
        gateway = ModelGateway({"evaluation": {"provider": "anthropic"}})
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with mock.patch.object(
                ModelGateway, "_synthesize_with_anthropic", side_effect=RuntimeError("api down")
            ):
                findings = gateway.synthesize(self._two_items(gateway), BRIEF)
        self.assertNotIn("## Synthesis", findings)
        self.assertIn("## Relevant Items", findings)

    def test_findings_contain_titles_sorted_by_score(self):
        gateway = ModelGateway()
        low = gateway.evaluate(_item("Nothing related at all in this text body whatsoever."), BRIEF)
        high = gateway.evaluate(
            _item("Agentic research platforms for knowledge work explained.", title="Platform deep dive"),
            BRIEF,
        )
        findings = gateway.synthesize([low, high], BRIEF)
        self.assertIn("# Findings", findings)
        self.assertIn("Platform deep dive", findings)
        self.assertLess(
            findings.index(f"Relevance: {high.relevance_score}/5"),
            findings.index(f"Relevance: {low.relevance_score}/5"),
        )


if __name__ == "__main__":
    unittest.main()
