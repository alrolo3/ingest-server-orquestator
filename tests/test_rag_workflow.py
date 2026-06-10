import unittest
from pathlib import Path


class RagWorkflowTest(unittest.TestCase):
    def test_workflow_promotes_title_semantic_retrieval(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / "elastic_integration"
            / "rag-workflow.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("title_semantic", workflow)
        self.assertGreaterEqual(workflow.count("title_semantic:"), 4)
        self.assertIn("clean_title^6", workflow)
        self.assertIn("heavily promoted title semantic branches", workflow)


if __name__ == "__main__":
    unittest.main()
