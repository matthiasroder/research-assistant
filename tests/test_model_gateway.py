from __future__ import annotations

import json
import os
import unittest
import urllib.error
from unittest import mock

from research_platform.execution import BudgetTracker
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
        self.assertEqual(evaluated.execution.status, "degraded")
        self.assertEqual(evaluated.execution.outcome_code, "fallback_used")

    def test_strict_missing_credentials_fails_without_local_success(self):
        gateway = ModelGateway(
            {"evaluation": {"provider": "anthropic", "on_missing_credentials": "fail"}}
        )
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            evaluated = gateway.evaluate(_item("agentic research platforms text"), BRIEF)
        self.assertEqual(evaluated.execution.status, "failed")
        self.assertEqual(evaluated.execution.outcome_code, "missing_credentials")
        self.assertEqual(evaluated.grounded_claims, [])

    def test_grounded_claim_has_exact_range_and_hashes(self):
        gateway = ModelGateway()
        item = _item("Prefix. Exact evidence sentence for the claim. Suffix.")
        evaluated = gateway._evaluated_from_data(
            item,
            {
                "relevance_score": 4,
                "grounded_claims": [
                    {
                        "text": "The item contains exact evidence.",
                        "evidence_excerpt": "Exact evidence sentence for the claim.",
                    }
                ],
                "uncertainties": [],
                "tags": ["evidence"],
            },
        )
        evidence = evaluated.grounded_claims[0].evidence[0]
        self.assertEqual(evaluated.grounded_claims[0].text, evidence.excerpt)
        self.assertEqual(item.text[evidence.start : evidence.end], evidence.excerpt)
        self.assertEqual(len(evidence.text_sha256), 64)
        self.assertEqual(len(evidence.excerpt_sha256), 64)
        self.assertLessEqual(len(evidence.excerpt), 300)

    def test_non_exact_or_oversized_evidence_is_rejected(self):
        gateway = ModelGateway()
        item = _item("Exact source sentence.")
        for excerpt in ("Paraphrased sentence.", "x" * 301):
            with self.assertRaisesRegex(ValueError, "no exactly grounded claims"):
                gateway._evaluated_from_data(
                    item,
                    {
                        "relevance_score": 4,
                        "grounded_claims": [{"text": "Claim", "evidence_excerpt": excerpt}],
                        "uncertainties": [],
                        "tags": [],
                    },
                )

    def test_invented_provider_claims_cannot_borrow_unrelated_exact_evidence(self):
        gateway = ModelGateway()
        evidence = "A pilot reported three donor conversations."
        item = _item(evidence)
        for invented_claim in (
            "The pilot will outperform every alternative.",
            "The pilot guarantees major gifts.",
        ):
            with self.subTest(invented_claim=invented_claim):
                evaluated = gateway._evaluated_from_data(
                    item,
                    {
                        "relevance_score": 4,
                        "grounded_claims": [
                            {
                                "text": invented_claim,
                                "evidence_excerpt": evidence,
                            }
                        ],
                        "uncertainties": [],
                        "tags": [],
                    },
                )
                claim = evaluated.grounded_claims[0]
                self.assertEqual(claim.text, evidence)
                self.assertNotIn("will outperform", claim.text)
                self.assertNotIn("guarantees major gifts", claim.text)

    def test_provider_diagnostic_prose_is_discarded_everywhere(self):
        gateway = ModelGateway()
        evidence = "A pilot reported three donor conversations."
        dangerous = "The pilot guarantees major gifts"
        evaluated = gateway._evaluated_from_data(
            _item(evidence),
            {
                "relevance_score": 4,
                "grounded_claims": [
                    {"text": dangerous, "evidence_excerpt": evidence}
                ],
                "rationale": dangerous,
                "uncertainties": [dangerous],
                "tags": [dangerous],
            },
        )

        self.assertNotIn(dangerous, json.dumps(evaluated.to_dict()))
        self.assertNotIn(dangerous, gateway.synthesize([evaluated], BRIEF))
        self.assertEqual(evaluated.uncertainties, [])
        self.assertEqual(evaluated.tags, [])
        self.assertEqual(evaluated.rationale, "Validated 1 exact evidence claim(s).")

    def test_model_prompt_sanitizes_every_visible_url(self):
        gateway = ModelGateway()
        item = _item(
            "Read https://content.example/report?key=text-secret&topic=safe for context."
        )
        item.url = (
            "https://user:password@provider.example/report?topic=safe"
            "&X-Amz-Signature=url-secret"
        )
        brief = ResearchBrief(
            question=(
                "Review https://brief.example/?credential=brief-secret&topic=research"
            ),
            mode="analyze-url",
        )

        prompt = gateway._evaluation_prompt(item, brief)

        for secret in ("password", "text-secret", "url-secret", "brief-secret"):
            self.assertNotIn(secret, prompt)
        self.assertIn("topic=safe", prompt)
        self.assertIn("topic=research", prompt)

    def test_transient_model_failure_retries_three_total_attempts(self):
        gateway = ModelGateway(
            {"evaluation": {"provider": "anthropic", "on_error": "fail"}},
            execution_config={"retries": {"max_attempts": 3}},
            sleeper=lambda _delay: None,
        )
        successful = gateway._evaluate_locally(_item("Agentic research platforms text."), BRIEF)
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with mock.patch.object(
                gateway,
                "_evaluate_with_anthropic",
                side_effect=[TimeoutError("one"), TimeoutError("two"), successful],
            ) as api:
                evaluated = gateway.evaluate(_item("Agentic research platforms text."), BRIEF)
        self.assertEqual(api.call_count, 3)
        self.assertEqual(evaluated.execution.status, "succeeded")
        self.assertEqual(evaluated.execution.attempts, 3)

    def test_authentication_failure_is_not_retried(self):
        gateway = ModelGateway(
            {"evaluation": {"provider": "anthropic", "on_error": "fail"}},
            sleeper=lambda _delay: None,
        )
        error = urllib.error.HTTPError("https://provider.example", 401, "unauthorized", {}, None)
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with mock.patch.object(gateway, "_evaluate_with_anthropic", side_effect=error) as api:
                evaluated = gateway.evaluate(_item("Agentic research platforms text."), BRIEF)
        self.assertEqual(api.call_count, 1)
        self.assertEqual(evaluated.execution.error_code, "authentication_failed")

    def test_budget_exhaustion_prevents_provider_call(self):
        budget = BudgetTracker({"max_provider_attempts_total": 0})
        gateway = ModelGateway(
            {"evaluation": {"provider": "anthropic", "on_error": "fail"}},
            budget=budget,
        )
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with mock.patch.object(gateway, "_evaluate_with_anthropic") as api:
                evaluated = gateway.evaluate(_item("Agentic research platforms text."), BRIEF)
        api.assert_not_called()
        self.assertEqual(evaluated.execution.outcome_code, "budget_exhausted")
        self.assertEqual(budget.snapshot().status, "exhausted")

    def test_elapsed_budget_exhaustion_prevents_provider_call(self):
        budget = BudgetTracker({"max_elapsed_seconds": 0})
        gateway = ModelGateway(
            {"evaluation": {"provider": "anthropic", "on_error": "fail"}},
            budget=budget,
        )
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with mock.patch.object(gateway, "_evaluate_with_anthropic") as api:
                evaluated = gateway.evaluate(_item("Agentic research platforms text."), BRIEF)
        api.assert_not_called()
        self.assertEqual(evaluated.execution.outcome_code, "budget_exhausted")

    def test_total_evidence_cap_can_be_lower_than_per_excerpt_cap(self):
        gateway = ModelGateway(
            execution_config={
                "privacy": {
                    "max_evidence_excerpt_chars": 300,
                    "max_evidence_total_chars_per_item": 100,
                }
            }
        )
        evaluated = gateway.evaluate(_item("x" * 500), BRIEF)
        total = sum(
            len(evidence.excerpt)
            for claim in evaluated.grounded_claims
            for evidence in claim.evidence
        )
        self.assertEqual(total, 100)


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
        items = self._two_items(gateway)
        claim_id = items[0].grounded_claims[0].id
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with mock.patch.object(
                ModelGateway,
                "_synthesize_with_anthropic",
                return_value=f"- Theme across items. [claim:{claim_id}]",
            ) as api:
                findings = gateway.synthesize(items, BRIEF)
        api.assert_called_once()
        self.assertIn("## Synthesis", findings)
        self.assertIn(items[0].grounded_claims[0].text, findings)
        self.assertNotIn("Theme across items", findings)
        self.assertLess(findings.index("## Synthesis"), findings.index("## Relevant Items"))

    def test_synthesis_cannot_attach_invented_prose_to_valid_claim_id(self):
        gateway = ModelGateway()
        items = self._two_items(gateway)
        claim = items[0].grounded_claims[0]
        validated = gateway._validate_synthesis(
            f"- Apples will outperform every alternative [claim:{claim.id}]", items
        )
        self.assertNotIn("Apples will outperform", validated)
        self.assertEqual(validated, f"- {claim.text} [claim:{claim.id}]")

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
