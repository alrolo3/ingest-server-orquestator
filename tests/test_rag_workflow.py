import unittest
from pathlib import Path


class RagWorkflowTest(unittest.TestCase):
    def test_workflow_uses_v4_sparse_semantic_retrieval(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / "elastic_integration"
            / "rag-workflow.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("open-rag-embeddings-v4", workflow)
        self.assertIn("field: content_dense", workflow)
        self.assertIn("field: content_sparse", workflow)
        self.assertNotIn("field: content\n", workflow)
        self.assertGreaterEqual(workflow.count("field: clean_title"), 4)
        self.assertGreaterEqual(workflow.count("field: headings"), 4)
        self.assertNotIn("clean_title^", workflow)
        self.assertNotIn("headings^", workflow)
        self.assertNotIn("title_semantic", workflow)
        self.assertNotIn("title_sparse", workflow)

    def test_workflow_v2_uses_only_sparse_and_dense_semantic_retrieval(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / "elastic_integration"
            / "rag-workflow-v2.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("open-rag-embeddings-v4", workflow)
        self.assertIn("field: content_dense", workflow)
        self.assertIn("field: content_sparse", workflow)
        self.assertNotIn("field: content\n", workflow)
        self.assertIn("field: clean_title", workflow)
        self.assertIn("field: headings", workflow)
        self.assertIn("standalone_question", workflow)
        self.assertIn("rrf_sparse_dense_retrieval", workflow)

        self.assertNotIn("query_en", workflow)
        self.assertNotIn("query_es", workflow)
        self.assertNotIn("content_lex", workflow)
        self.assertNotIn("multi_match", workflow)
        self.assertNotIn("BM25", workflow)
        self.assertNotIn("Translation", workflow)
        self.assertNotIn("translation", workflow)
        for boost in ("^2", "^3", "^4", "^5"):
            self.assertNotIn(boost, workflow)


if __name__ == "__main__":
    unittest.main()
