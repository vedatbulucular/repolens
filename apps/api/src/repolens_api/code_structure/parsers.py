"""Parser selection for supported source-file extensions."""

from typing import Protocol

from repolens_api.code_structure.contracts import ParsedSourceStructure
from repolens_api.code_structure.javascript_parser import JavaScriptSourceParser
from repolens_api.code_structure.python_parser import PythonSourceParser


class SourceParser(Protocol):
    """Typed parser boundary shared by supported languages."""

    def parse(
        self,
        relative_path: str,
        language: str,
        source: str,
    ) -> ParsedSourceStructure:
        """Return safe source structure without evaluating code."""
        ...


class SourceParserRegistry:
    """Own the minimum supported parser implementations."""

    def __init__(self, *, max_imported_names_per_import: int) -> None:
        self._python = PythonSourceParser(
            max_imported_names_per_import=max_imported_names_per_import
        )
        self._javascript = JavaScriptSourceParser(
            max_imported_names_per_import=max_imported_names_per_import
        )

    def for_language(self, language: str) -> SourceParser:
        """Return the fixed parser for an already supported language."""
        if language == "Python":
            return self._python
        if language in {"JavaScript", "TypeScript"}:
            return self._javascript
        raise ValueError("unsupported source language")
