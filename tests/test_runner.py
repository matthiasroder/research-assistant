import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from research_platform.execution import BudgetTracker
from research_platform.model_gateway import ModelGateway
from research_platform.models import (
    EvaluatedItem,
    ResearchBrief,
    ResearchItem,
    RunHealth,
    RunResult,
    Source,
)
from research_platform.models import SourceFetchOutcome
from research_platform.runner import (
    DiscoveryError,
    FetchBatch,
    acknowledge_run,
    fetch_items_with_outcomes,
    load_source_brief,
    load_source_file,
    make_run_id,
    run,
    validate_evaluated_items,
    write_run,
)
from research_platform.state import SeenStore


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
        today = datetime.now(ZoneInfo("Europe/Vienna")).strftime("%Y-%m-%d")
        self.assertTrue(run_id.startswith(f"{today}-"))
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
        brief = ResearchBrief(question="test", mode="analyze-url")
        return RunResult(
            run_id="2026-01-01-test",
            brief=brief,
            sources=[Source.from_url("https://example.com")],
            items=[item],
            evaluated_items=[ModelGateway().evaluate(item, brief)],
            findings_markdown="# Findings\n",
        )

    def test_claim_that_cannot_fit_is_dropped_instead_of_truncated(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            write_run(run_dir, self._result("x" * 2000), max_item_text_chars=100)
            items = json.loads((run_dir / "items.json").read_text())
            evaluated = json.loads((run_dir / "evaluated_items.json").read_text())
            manifest = json.loads((run_dir / "run.json").read_text())
        self.assertEqual(items[0]["text"], "")
        self.assertEqual(evaluated, [])
        self.assertEqual(manifest["counts"]["evaluated_items"], 0)
        self.assertEqual(manifest["counts"]["grounded_claims"], 0)

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
            self.assertEqual(manifest["schema_version"], 2)
            self.assertIn("health", manifest)
            self.assertIn("budget", manifest)
            self.assertIn("acknowledgment", manifest)
            for name in manifest["files"]:
                self.assertTrue((run_dir / name).exists())

    def test_provider_record_metadata_is_redacted_in_artifacts(self):
        secret = "provider-only full text " + ("x" * 1000)
        item = _item("short text")
        item.metadata = {"provider_record": {"full_text": secret}, "safe": "metadata"}
        brief = ResearchBrief(question="test", mode="monitor-sources")
        result = RunResult(
            run_id="2026-01-01-test",
            brief=brief,
            sources=[Source(id="api", type="api_json", name="API", url="https://provider.example")],
            items=[item],
            evaluated_items=[ModelGateway().evaluate(item, brief)],
            findings_markdown="# Findings\n",
        )

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            write_run(run_dir, result, max_item_text_chars=100)
            items_text = (run_dir / "items.json").read_text()
            evaluated_text = (run_dir / "evaluated_items.json").read_text()
            items = json.loads(items_text)
            evaluated = json.loads(evaluated_text)

        self.assertNotIn(secret, items_text)
        self.assertNotIn(secret, evaluated_text)
        self.assertNotIn("provider_record", items[0]["metadata"])
        self.assertTrue(items[0]["metadata"]["provider_record_redacted"])
        self.assertNotIn("provider_record", evaluated[0]["item"]["metadata"])
        self.assertEqual(items[0]["metadata"]["safe"], "metadata")

    def test_source_artifact_recursively_removes_credentials_and_sensitive_query_params(self):
        source = Source(
            id="api",
            type="api_json",
            name="API",
            url=(
                "https://user:password@provider.example/search?q=safe"
                "&api_key=url-secret&access_token=url-token#token=fragment-secret"
            ),
            access={
                "method": "api_key",
                "headers": {
                    "Authorization": "Bearer header-secret",
                    "Cookie": "session=cookie-secret",
                },
                "api_key_env": "PRIVATE_API_KEY",
                "safe": "kept",
            },
            metadata={
                "provider_record": {"full_text": "provider-secret"},
                "request": {"headers": {"X-Api-Key": "request-secret"}},
                "nested": {
                    "token": "nested-secret",
                    "safe_url": "https://example.com/page?topic=kept&token=embedded-secret",
                    "safe": "metadata-kept",
                },
            },
        )
        result = self._result("text")
        result.sources = [source]
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            write_run(run_dir, result)
            serialized = (run_dir / "sources.json").read_text()
            data = json.loads(serialized)[0]

        for secret in (
            "password",
            "url-secret",
            "url-token",
            "fragment-secret",
            "header-secret",
            "cookie-secret",
            "PRIVATE_API_KEY",
            "provider-secret",
            "request-secret",
            "nested-secret",
            "embedded-secret",
        ):
            self.assertNotIn(secret, serialized)
        self.assertEqual(data["url"], "https://provider.example/search?q=safe")
        self.assertEqual(data["access"], {"method": "api_key", "safe": "kept"})
        self.assertEqual(data["metadata"]["nested"]["safe"], "metadata-kept")
        self.assertEqual(
            data["metadata"]["nested"]["safe_url"], "https://example.com/page?topic=kept"
        )

    def test_item_storage_cap_is_applied_to_artifacts(self):
        item = _item("x" * 500)
        item.access_rights = {"store_full_text": False, "max_store_chars": 50}
        brief = ResearchBrief(question="test", mode="monitor-sources")
        result = RunResult(
            run_id="2026-01-01-test",
            brief=brief,
            sources=[Source.from_url("https://example.com")],
            items=[item],
            evaluated_items=[ModelGateway().evaluate(item, brief)],
            findings_markdown="# Findings\n",
        )

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            write_run(run_dir, result, max_item_text_chars=1000)
            item_data = json.loads((run_dir / "items.json").read_text())[0]

        self.assertEqual(item_data["text"], "x" * 50)

    def test_zero_storage_cap_retains_no_item_or_evidence_text(self):
        item = _item("Exact evidence about agentic research platforms for knowledge work.")
        evaluated = ModelGateway().evaluate(
            item,
            ResearchBrief(question="agentic research platforms", mode="analyze-url"),
        )
        result = RunResult(
            run_id="2026-01-01-test",
            brief=ResearchBrief(question="test", mode="analyze-url"),
            sources=[Source.from_url("https://example.com")],
            items=[item],
            evaluated_items=[evaluated],
            findings_markdown="# Findings\n",
            health=RunHealth("2026-01-01-test", "healthy"),
            acknowledgment={"eligible_item_ids": [item.id], "committed": False},
        )

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            write_run(run_dir, result, max_item_text_chars=0, max_evidence_chars=700)
            stored_item = json.loads((run_dir / "items.json").read_text())[0]
            stored_evaluated = json.loads((run_dir / "evaluated_items.json").read_text())

        self.assertEqual(stored_item["text"], "")
        self.assertEqual(stored_evaluated, [])

    def test_findings_are_rebuilt_from_capped_sanitized_artifacts(self):
        evidence = "A pilot reported three donor conversations."
        dangerous = "The pilot guarantees major gifts"
        credential = "aws-signature-secret"
        item = _item(evidence)
        item.url = (
            "https://provider.example/report?topic=safe"
            f"&X-Amz-Signature={credential}"
        )
        evaluated = ModelGateway().evaluate(
            item,
            ResearchBrief(question="donor research", mode="analyze-url"),
        )
        evaluated.grounded_claims[0].text = dangerous
        evaluated.rationale = dangerous
        evaluated.uncertainties = [dangerous]
        evaluated.tags = [dangerous]
        result = RunResult(
            run_id="2026-01-01-test",
            brief=ResearchBrief(question="donor research", mode="analyze-url"),
            sources=[Source.from_url(item.url)],
            items=[item],
            evaluated_items=[evaluated],
            findings_markdown=f"# Unsafe pre-render\n\n{dangerous}\n\n{evidence}\n",
        )

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            write_run(
                run_dir,
                result,
                max_item_text_chars=0,
                max_evidence_chars=0,
            )
            artifacts = {
                path.name: path.read_text()
                for path in run_dir.iterdir()
                if path.is_file()
            }

        self.assertNotIn("Unsafe pre-render", artifacts["findings.md"])
        self.assertNotIn(evidence, artifacts["findings.md"])
        for serialized in artifacts.values():
            self.assertNotIn(dangerous, serialized)
            self.assertNotIn(credential, serialized)
        self.assertIn("topic=safe", artifacts["items.json"])

    def test_late_evidence_is_rebased_into_committed_bundle(self):
        evidence = "A late exact excerpt remains independently verifiable."
        item = _item(("x" * 900) + evidence)
        brief = ResearchBrief(question="late evidence", mode="analyze-url")
        evaluated = ModelGateway()._evaluated_from_data(
            item,
            {
                "relevance_score": 4,
                "grounded_claims": [
                    {"text": "provider prose", "evidence_excerpt": evidence}
                ],
            },
        )
        result = RunResult(
            run_id="2026-01-01-test",
            brief=brief,
            sources=[Source.from_url("https://example.com")],
            items=[item],
            evaluated_items=[evaluated],
            findings_markdown="# ignored\n",
        )

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            write_run(run_dir, result, max_item_text_chars=700, max_evidence_chars=700)
            items = json.loads((run_dir / "items.json").read_text())
            evaluated_rows = json.loads((run_dir / "evaluated_items.json").read_text())

        self.assertEqual(items[0]["text"], evidence)
        self.assertEqual(evaluated_rows[0]["item"], items[0])
        ref = evaluated_rows[0]["grounded_claims"][0]["evidence"][0]
        self.assertEqual((ref["start"], ref["end"]), (0, len(evidence)))
        validate_evaluated_items(items, evaluated_rows)

        tampered_items = copy.deepcopy(items)
        tampered_evaluated = copy.deepcopy(evaluated_rows)
        tampered_items[0]["text"] += " tampered"
        tampered_evaluated[0]["item"] = copy.deepcopy(tampered_items[0])
        with self.assertRaisesRegex(ValueError, "validation failed"):
            validate_evaluated_items(tampered_items, tampered_evaluated)

    def test_duplicate_excerpts_have_one_deterministic_committed_mapping(self):
        evidence = "The same exact excerpt supports the retained observation."
        item = _item(evidence)
        evaluated = ModelGateway()._evaluated_from_data(
            item,
            {
                "relevance_score": 4,
                "grounded_claims": [
                    {"text": "first", "evidence_excerpt": evidence},
                    {"text": "second", "evidence_excerpt": evidence},
                ],
            },
        )
        result = RunResult(
            run_id="2026-01-01-test",
            brief=ResearchBrief(question="duplicates", mode="analyze-url"),
            sources=[Source.from_url("https://example.com")],
            items=[item],
            evaluated_items=[evaluated],
            findings_markdown="# ignored\n",
        )

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            write_run(run_dir, result)
            items = json.loads((run_dir / "items.json").read_text())
            evaluated_rows = json.loads((run_dir / "evaluated_items.json").read_text())

        self.assertEqual(items[0]["text"], evidence)
        self.assertEqual(len(evaluated_rows[0]["grounded_claims"]), 1)
        validate_evaluated_items(items, evaluated_rows)

    def test_one_dropped_item_clears_all_acknowledgment_eligibility(self):
        brief = ResearchBrief(question="bounded evidence", mode="monitor-sources")
        short_item = _item("Short exact proof.")
        long_item = ResearchItem(
            id="item-2",
            source_id="source-2",
            source_type="webpage",
            title="Second item",
            url="https://example.com/second",
            text="This exact evidence is intentionally too long for the configured cap.",
        )
        short_evaluated = ModelGateway().evaluate(short_item, brief)
        long_evaluated = ModelGateway().evaluate(long_item, brief)
        result = RunResult(
            run_id="2026-01-01-test",
            brief=brief,
            sources=[
                Source.from_url("https://example.com/first"),
                Source.from_url("https://example.com/second"),
            ],
            items=[short_item, long_item],
            evaluated_items=[short_evaluated, long_evaluated],
            findings_markdown="# ignored\n",
            health=RunHealth("2026-01-01-test", "healthy"),
            acknowledgment={
                "mode": "external",
                "eligible_item_ids": [short_item.id, long_item.id],
                "committed": False,
                "committed_at": None,
            },
        )

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            write_run(
                run_dir,
                result,
                max_item_text_chars=100,
                max_evidence_chars=20,
            )
            evaluated_rows = json.loads((run_dir / "evaluated_items.json").read_text())
            manifest = json.loads((run_dir / "run.json").read_text())

        self.assertEqual([row["item"]["id"] for row in evaluated_rows], [short_item.id])
        self.assertEqual(result.health.status, "failed")
        self.assertEqual(result.acknowledgment["eligible_item_ids"], [])
        self.assertEqual(manifest["acknowledgment"]["eligible_item_ids"], [])

    def test_item_level_zero_storage_cap_is_fail_closed(self):
        item = _item("restricted text")
        item.access_rights = {"store_full_text": False, "max_store_chars": 0}
        result = self._result("unused")
        result.items = [item]
        result.evaluated_items = [EvaluatedItem(item=item, relevance_score=3, summary="s")]

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            write_run(run_dir, result, max_item_text_chars=700)
            stored_item = json.loads((run_dir / "items.json").read_text())[0]

        self.assertEqual(stored_item["text"], "")


class FetchTimeoutTests(unittest.TestCase):
    def test_source_timeout_is_bounded_by_remaining_run_budget(self):
        source = Source(
            id="source-1",
            type="webpage",
            name="Source",
            url="https://example.com",
        )
        connector = mock.Mock()
        connector.fetch.return_value = []
        budget = BudgetTracker({"max_elapsed_seconds": 10.0})

        with mock.patch.dict(
            "research_platform.runner.CONNECTORS", {"webpage": connector}, clear=False
        ):
            with mock.patch(
                "research_platform.execution.time.monotonic",
                return_value=budget.started_at + 8.0,
            ):
                fetch_items_with_outcomes(
                    [source],
                    retry_config={"source_timeout_seconds": 30},
                    budget=budget,
                )

        connector.fetch.assert_called_once()
        self.assertAlmostEqual(connector.fetch.call_args.kwargs["timeout"], 2.0)


class RunTests(unittest.TestCase):
    def test_research_topic_without_discovered_sources_fails(self):
        brief = ResearchBrief(question="agentic research platforms", mode="research-topic")
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("research_platform.runner.discover_sources", return_value=[]):
                with self.assertRaisesRegex(DiscoveryError, "No sources were discovered"):
                    run(brief=brief, urls=[], config={}, repo_root=Path(tmp))

    def _source_item_batch(self):
        source = Source(id="source-1", type="webpage", name="Source", url="https://example.com")
        item = _item("This is exact evidence about agentic research platforms for knowledge work.")
        return source, FetchBatch(
            [item],
            [SourceFetchOutcome(source.id, source.type, "succeeded", "ok", 1)],
        )

    def test_external_acknowledgment_commits_only_after_explicit_call(self):
        brief = ResearchBrief(question="agentic research platforms", mode="monitor-sources")
        source, batch = self._source_item_batch()
        config = {
            "models": {"evaluation": {"provider": "local"}},
            "execution": {"acknowledgment_mode": "external"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch("research_platform.runner.fetch_items_with_outcomes", return_value=batch):
                result, run_dir = run(brief, [], config, root, configured_sources=[source])
            self.assertEqual(result.health.status, "healthy")
            self.assertFalse(result.acknowledgment["committed"])
            self.assertFalse(SeenStore(root / "knowledge" / "platform_state.json").has_seen("item-1"))
            acknowledge_run(run_dir, root / "knowledge" / "platform_state.json")
            self.assertTrue(SeenStore(root / "knowledge" / "platform_state.json").has_seen("item-1"))
            manifest = json.loads((run_dir / "run.json").read_text())
            self.assertTrue(manifest["acknowledgment"]["committed"])

    def test_external_acknowledgment_rejects_tampered_or_missing_artifacts(self):
        cases = (
            ("tampered_items", "items.json", "tamper"),
            ("tampered_evaluated", "evaluated_items.json", "tamper"),
            ("deleted_items", "items.json", "delete"),
            ("deleted_evaluated", "evaluated_items.json", "delete"),
            ("malformed_items", "items.json", "malformed"),
            ("malformed_evaluated", "evaluated_items.json", "malformed"),
        )
        for case, filename, mutation in cases:
            with self.subTest(case=case):
                brief = ResearchBrief(
                    question="agentic research platforms", mode="monitor-sources"
                )
                source, batch = self._source_item_batch()
                config = {
                    "models": {"evaluation": {"provider": "local"}},
                    "execution": {"acknowledgment_mode": "external"},
                }
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    with mock.patch(
                        "research_platform.runner.fetch_items_with_outcomes",
                        return_value=batch,
                    ):
                        _, run_dir = run(
                            brief, [], config, root, configured_sources=[source]
                        )
                    artifact_path = run_dir / filename
                    if mutation == "delete":
                        artifact_path.unlink()
                    elif mutation == "malformed":
                        artifact_path.write_text('{"not": "a list"}')
                    else:
                        data = json.loads(artifact_path.read_text())
                        data[0]["title" if filename == "items.json" else "summary"] = (
                            "post-write tamper"
                        )
                        artifact_path.write_text(json.dumps(data))

                    state_path = root / "knowledge" / "platform_state.json"
                    with self.assertRaises(ValueError):
                        acknowledge_run(run_dir, state_path)
                    self.assertFalse(state_path.exists())
                    manifest = json.loads((run_dir / "run.json").read_text())
                    self.assertFalse(manifest["acknowledgment"]["committed"])

    def test_external_acknowledgment_rejects_manifest_eligibility_tamper(self):
        brief = ResearchBrief(
            question="agentic research platforms", mode="monitor-sources"
        )
        source, batch = self._source_item_batch()
        config = {
            "models": {"evaluation": {"provider": "local"}},
            "execution": {"acknowledgment_mode": "external"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch(
                "research_platform.runner.fetch_items_with_outcomes", return_value=batch
            ):
                _, run_dir = run(brief, [], config, root, configured_sources=[source])
            manifest_path = run_dir / "run.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["acknowledgment"]["eligible_item_ids"].append("unrelated-item")
            manifest_path.write_text(json.dumps(manifest))

            state_path = root / "knowledge" / "platform_state.json"
            with self.assertRaisesRegex(ValueError, "eligibility"):
                acknowledge_run(run_dir, state_path)
            self.assertFalse(state_path.exists())
            persisted = json.loads(manifest_path.read_text())
            self.assertFalse(persisted["acknowledgment"]["committed"])

    def test_external_acknowledgment_requires_nonempty_string_run_identity(self):
        for invalid_run_id in (123, True, "", "   "):
            with self.subTest(invalid_run_id=invalid_run_id):
                brief = ResearchBrief(
                    question="agentic research platforms", mode="monitor-sources"
                )
                source, batch = self._source_item_batch()
                config = {
                    "models": {"evaluation": {"provider": "local"}},
                    "execution": {"acknowledgment_mode": "external"},
                }
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    with mock.patch(
                        "research_platform.runner.fetch_items_with_outcomes",
                        return_value=batch,
                    ):
                        _, run_dir = run(
                            brief, [], config, root, configured_sources=[source]
                        )
                    manifest_path = run_dir / "run.json"
                    manifest = json.loads(manifest_path.read_text())
                    manifest["run_id"] = invalid_run_id
                    manifest["health"]["run_id"] = invalid_run_id
                    manifest_path.write_text(json.dumps(manifest))

                    state_path = root / "knowledge" / "platform_state.json"
                    with self.assertRaisesRegex(ValueError, "same healthy run"):
                        acknowledge_run(run_dir, state_path)
                    self.assertFalse(state_path.exists())
                    persisted = json.loads(manifest_path.read_text())
                    self.assertFalse(persisted["acknowledgment"]["committed"])

    def test_degraded_fallback_is_not_eligible_or_acknowledged(self):
        brief = ResearchBrief(question="agentic research platforms", mode="monitor-sources")
        source, batch = self._source_item_batch()
        config = {
            "models": {"evaluation": {"provider": "anthropic"}},
            "execution": {"acknowledgment_mode": "after_run"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
                with mock.patch("research_platform.runner.fetch_items_with_outcomes", return_value=batch):
                    result, _ = run(brief, [], config, root, configured_sources=[source])
            self.assertEqual(result.health.status, "degraded")
            self.assertEqual(result.acknowledgment["eligible_item_ids"], [])
            self.assertFalse(result.acknowledgment["committed"])
            self.assertFalse(SeenStore(root / "knowledge" / "platform_state.json").has_seen("item-1"))

    def test_source_budget_exhaustion_is_observable_and_blocks_fetch(self):
        brief = ResearchBrief(question="agentic research platforms", mode="monitor-sources")
        source, _ = self._source_item_batch()
        config = {"execution": {"budgets": {"max_sources_total": 0}}}
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("research_platform.runner.fetch_items_with_outcomes") as fetch:
                result, run_dir = run(brief, [], config, Path(tmp), configured_sources=[source])
            fetch.assert_not_called()
            self.assertEqual(result.health.status, "failed")
            self.assertEqual(result.budget.status, "exhausted")
            manifest = json.loads((run_dir / "run.json").read_text())
            self.assertEqual(manifest["budget"]["exhausted_limit"], "max_sources_total")

    def test_empty_source_outcome_is_distinct_and_not_a_failure(self):
        brief = ResearchBrief(question="agentic research platforms", mode="monitor-sources")
        source = Source(id="feed", type="rss", name="Feed", url="https://example.com/feed.xml")
        batch = FetchBatch(
            [], [SourceFetchOutcome(source.id, source.type, "empty", "empty_source", 0)]
        )
        config = {"execution": {"acknowledgment_mode": "external"}}
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("research_platform.runner.fetch_items_with_outcomes", return_value=batch):
                result, run_dir = run(brief, [], config, Path(tmp), configured_sources=[source])
            self.assertEqual(result.health.status, "healthy")
            manifest = json.loads((run_dir / "run.json").read_text())
            self.assertEqual(manifest["source_outcomes"][0]["outcome_code"], "empty_source")

    def test_evidence_that_exceeds_collective_cap_is_dropped(self):
        brief = ResearchBrief(question="agentic research platforms", mode="analyze-url")
        item = _item("This exact evidence sentence is long enough to be extracted and retained.")
        evaluated = ModelGateway().evaluate(item, brief)
        result = RunResult(
            run_id="2026-01-01-test",
            brief=brief,
            sources=[Source.from_url("https://example.com")],
            items=[item],
            evaluated_items=[evaluated],
            findings_markdown="# Findings\n",
            health=RunHealth("2026-01-01-test", "healthy"),
            acknowledgment={"eligible_item_ids": [item.id], "committed": False},
        )
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            write_run(run_dir, result, max_item_text_chars=100, max_evidence_chars=20)
            artifacts = json.loads((run_dir / "evaluated_items.json").read_text())
            items = json.loads((run_dir / "items.json").read_text())
            findings = (run_dir / "findings.md").read_text()
            manifest = json.loads((run_dir / "run.json").read_text())
        self.assertEqual(artifacts, [])
        self.assertEqual(items[0]["text"], "")
        self.assertNotIn(item.text, findings)
        self.assertEqual(result.health.status, "failed")
        self.assertIn("committed_evidence_unavailable", result.health.blocking_codes)
        self.assertEqual(result.acknowledgment["eligible_item_ids"], [])
        self.assertEqual(manifest["health"]["status"], "failed")
        self.assertIn("committed_evidence_unavailable", findings)


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
