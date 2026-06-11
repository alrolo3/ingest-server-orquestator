import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(SRC_DIR))

from processing.parsers.json_markdown import JsonToMarkdownPreprocessor


class JsonToMarkdownPreprocessorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.preprocessor = JsonToMarkdownPreprocessor()

    def test_flat_object_becomes_key_value_markdown(self) -> None:
        markdown = self.preprocessor.from_text(
            '{"name": "Alice", "age": 30, "active": true}',
            title="profile",
        )

        self.assertIn("# profile", markdown)
        self.assertIn("- `name`: Alice", markdown)
        self.assertIn("- `age`: 30", markdown)
        self.assertIn("- `active`: true", markdown)

    def test_array_of_objects_becomes_markdown_table(self) -> None:
        markdown = self.preprocessor.from_text(
            '{"users": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]}',
            title="users",
        )

        self.assertIn("## users", markdown)
        self.assertIn("| id | name |", markdown)
        self.assertIn("| --- | --- |", markdown)
        self.assertIn("| 1 | A |", markdown)
        self.assertIn("| 2 | B |", markdown)

    def test_nested_json_preserves_structure_with_headings(self) -> None:
        markdown = self.preprocessor.from_text(
            '{"person": {"address": {"city": "Madrid"}}, "items": ["a", {"b": 1}]}',
            title="nested",
        )

        self.assertIn("## person", markdown)
        self.assertIn("### address", markdown)
        self.assertIn("- `city`: Madrid", markdown)
        self.assertIn("## items", markdown)
        self.assertIn("1. a", markdown)
        self.assertIn("### Item 2", markdown)
        self.assertIn("- `b`: 1", markdown)

    def test_table_cells_escape_pipes_and_newlines(self) -> None:
        markdown = self.preprocessor.from_text(
            '{"rows": [{"text": "a|b\\nc"}]}',
            title="table",
        )

        self.assertIn("| a\\|b<br>c |", markdown)

    def test_invalid_json_raises_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid JSON input"):
            self.preprocessor.from_text("{", title="bad")


if __name__ == "__main__":
    unittest.main()
