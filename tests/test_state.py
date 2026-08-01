import json
import tempfile
import unittest
from pathlib import Path

from research_platform.state import SeenStore, StateCorruptionError


class SeenStoreTests(unittest.TestCase):
    def test_marks_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = SeenStore(path)
            store.mark_seen(["a", "b"])
            store.save()
            reloaded = SeenStore(path)
            self.assertTrue(reloaded.has_seen("a"))
            self.assertFalse(reloaded.has_seen("c"))

    def test_eviction_drops_oldest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = SeenStore(path, max_ids=3)
            store.mark_seen(["a", "b"])
            store.mark_seen(["c", "d"])
            store.save()
            self.assertFalse(store.has_seen("a"))
            self.assertTrue(store.has_seen("b"))
            self.assertTrue(store.has_seen("d"))
            reloaded = SeenStore(path, max_ids=3)
            self.assertEqual(reloaded.data["seen_item_ids"], ["b", "c", "d"])

    def test_duplicate_ids_are_not_double_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SeenStore(Path(tmp) / "state.json", max_ids=3)
            store.mark_seen(["a", "a", "b", "a"])
            store.save()
            self.assertEqual(store.data["seen_item_ids"], ["a", "b"])

    def test_corrupt_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text("{not json")
            with self.assertRaises(StateCorruptionError):
                SeenStore(path)
            self.assertEqual(path.read_text(), "{not json")

    def test_version_one_loads_and_saves_as_version_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text('{"seen_item_ids": ["old"]}')
            store = SeenStore(path)
            self.assertTrue(store.has_seen("old"))
            store.acknowledge(["new"], run_id="run-1")
            store.save()
            data = json.loads(path.read_text())
            self.assertEqual(data["schema_version"], 2)
            self.assertEqual(data["seen_item_ids"], ["old", "new"])
            self.assertEqual(data["item_status"]["new"]["status"], "acknowledged")

    def test_version_two_item_status_entry_must_be_an_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "seen_item_ids": [],
                        "item_status": {"item-1": "acknowledged"},
                    }
                )
            )
            with self.assertRaises(StateCorruptionError):
                SeenStore(path)

    def test_version_two_item_status_fields_are_validated(self):
        invalid_statuses = [
            {"status": "unknown"},
            {"status": "attempted", "attempt_count": True},
            {"status": "attempted", "attempt_count": -1},
            {"status": "acknowledged", "run_id": 123},
            {"status": "attempted", "unexpected": "value"},
        ]
        for item_status in invalid_statuses:
            with self.subTest(item_status=item_status):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "state.json"
                    path.write_text(
                        json.dumps(
                            {
                                "schema_version": 2,
                                "seen_item_ids": [],
                                "item_status": {"item-1": item_status},
                            }
                        )
                    )
                    with self.assertRaises(StateCorruptionError):
                        SeenStore(path)


if __name__ == "__main__":
    unittest.main()
