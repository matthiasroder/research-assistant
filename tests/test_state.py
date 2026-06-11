import tempfile
import unittest
from pathlib import Path

from research_platform.state import SeenStore


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

    def test_corrupt_file_resets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text("{not json")
            store = SeenStore(path)
            self.assertFalse(store.has_seen("a"))


if __name__ == "__main__":
    unittest.main()
