import unittest
from pathlib import Path


class WorkflowPinningTests(unittest.TestCase):
    def test_workflows_use_lockfile_and_verified_action_shas(self):
        repository = Path(__file__).resolve().parents[1]
        checkout_sha = "3d3c42e5aac5ba805825da76410c181273ba90b1"
        setup_python_sha = "5fda3b95a4ea91299a34e894583c3862153e4b97"
        for relative_path in (
            ".github/workflows/tests.yml",
            ".github/workflows/research-platform-monitor.yml",
        ):
            with self.subTest(workflow=relative_path):
                contents = (repository / relative_path).read_text()
                self.assertIn(f"actions/checkout@{checkout_sha}", contents)
                self.assertIn(f"actions/setup-python@{setup_python_sha}", contents)
                self.assertIn("python -m pip install -r requirements.lock", contents)
                self.assertNotIn("requirements.txt", contents)
                self.assertNotIn("pip install --upgrade", contents)


if __name__ == "__main__":
    unittest.main()
