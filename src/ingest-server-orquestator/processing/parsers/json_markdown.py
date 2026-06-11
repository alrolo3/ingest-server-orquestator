from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class JsonToMarkdownPreprocessor:
    """Convert arbitrary JSON data into retrieval-friendly Markdown."""

    def from_file(self, path: Path, *, title: str | None = None) -> str:
        try:
            raw = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"JSON file must be UTF-8 text: {path}") from exc
        return self.from_text(raw, title=title or path.stem)

    def from_text(self, raw: str, *, title: str = "JSON document") -> str:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON input: {exc.msg}") from exc

        lines = [f"# {self._heading(title)}", ""]
        lines.extend(self._render_value(data, level=2))
        return self._normalize_document(lines)

    def _render_value(self, value: Any, *, level: int) -> list[str]:
        if isinstance(value, Mapping):
            return self._render_object(value, level=level)
        if isinstance(value, list):
            return self._render_array(value, level=level)
        return [f"- value: {self._scalar_text(value)}", ""]

    def _render_object(self, value: Mapping[Any, Any], *, level: int) -> list[str]:
        if not value:
            return ["- empty object", ""]

        scalar_items = []
        nested_items = []
        for key, item in value.items():
            if self._is_scalar(item):
                scalar_items.append((str(key), item))
            else:
                nested_items.append((str(key), item))

        lines: list[str] = []
        if scalar_items:
            for key, item in scalar_items:
                lines.append(f"- `{key}`: {self._scalar_text(item)}")
            lines.append("")

        for key, item in nested_items:
            lines.append(f"{'#' * level} {self._heading(key)}")
            lines.append("")
            lines.extend(self._render_value(item, level=level + 1))

        return lines

    def _render_array(self, value: list[Any], *, level: int) -> list[str]:
        if not value:
            return ["- empty array", ""]

        if self._is_table_array(value):
            return self._render_table(value)

        lines: list[str] = []
        for index, item in enumerate(value, start=1):
            if self._is_scalar(item):
                lines.append(f"{index}. {self._scalar_text(item)}")
            else:
                lines.append(f"{'#' * level} Item {index}")
                lines.append("")
                lines.extend(self._render_value(item, level=level + 1))
        if lines and lines[-1] != "":
            lines.append("")
        return lines

    def _render_table(self, value: list[Any]) -> list[str]:
        rows = [dict(item) for item in value if isinstance(item, Mapping)]
        headers: list[str] = []
        for row in rows:
            for key in row:
                key_text = str(key)
                if key_text not in headers:
                    headers.append(key_text)

        lines = [
            "| " + " | ".join(self._table_cell(header) for header in headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        for row in rows:
            lines.append(
                "| "
                + " | ".join(
                    self._table_cell(self._cell_value(row.get(header)))
                    for header in headers
                )
                + " |"
            )
        lines.append("")
        return lines

    @staticmethod
    def _is_scalar(value: Any) -> bool:
        return value is None or isinstance(value, (str, int, float, bool))

    def _is_table_array(self, value: list[Any]) -> bool:
        return (
            bool(value)
            and all(isinstance(item, Mapping) for item in value)
            and any(item for item in value)
        )

    def _cell_value(self, value: Any) -> str:
        if self._is_scalar(value):
            return self._scalar_text(value)
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _scalar_text(value: Any) -> str:
        if value is None:
            return "null"
        if value is True:
            return "true"
        if value is False:
            return "false"
        return str(value)

    @staticmethod
    def _table_cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\r\n", "\n").replace("\n", "<br>")

    @staticmethod
    def _heading(value: str) -> str:
        heading = " ".join(str(value or "").split()).strip()
        return heading or "Untitled"

    @staticmethod
    def _normalize_document(lines: list[str]) -> str:
        while lines and lines[-1] == "":
            lines.pop()
        return "\n".join(lines) + "\n"
