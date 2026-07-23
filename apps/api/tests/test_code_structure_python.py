"""Tests for safe Python AST source-structure extraction."""

from repolens_api.code_structure.contracts import (
    SourceImportKind,
    SourceSymbolKind,
)
from repolens_api.code_structure.python_parser import PythonSourceParser


def _parser() -> PythonSourceParser:
    return PythonSourceParser(max_imported_names_per_import=10)


def test_python_parser_extracts_symbols_imports_scopes_and_visibility() -> None:
    source = '''"""function fake(): pass"""
# class Fake: pass
import os
import package.submodule as ignored_alias
from .helpers import Beta, alpha

def public(a, b=1, *args, **kwargs):
    def _nested(value):
        return value
    return _nested(a)

async def _hidden(value):
    return value

class Demo:
    def method(self, item):
        return item

    async def _private(self):
        return None
'''

    result = _parser().parse("src/module.py", "Python", source)

    assert result.has_syntax_errors is False
    assert result.parse_failed is False
    assert tuple(item.name for item in result.symbols) == (
        "public",
        "_nested",
        "_hidden",
        "Demo",
        "method",
        "_private",
    )
    assert tuple(item.qualified_name for item in result.symbols) == (
        "public",
        "public._nested",
        "_hidden",
        "Demo",
        "Demo.method",
        "Demo._private",
    )
    assert tuple(item.kind for item in result.symbols) == (
        SourceSymbolKind.FUNCTION,
        SourceSymbolKind.FUNCTION,
        SourceSymbolKind.ASYNC_FUNCTION,
        SourceSymbolKind.CLASS,
        SourceSymbolKind.METHOD,
        SourceSymbolKind.ASYNC_METHOD,
    )
    assert tuple(item.parameter_count for item in result.symbols) == (4, 1, 1, 0, 2, 1)
    assert tuple(item.parent_name for item in result.symbols) == (
        None,
        "public",
        None,
        None,
        "Demo",
        "Demo",
    )
    assert tuple(item.is_public for item in result.symbols) == (
        True,
        False,
        False,
        True,
        True,
        False,
    )
    assert all(item.is_exported is False for item in result.symbols)
    assert all(item.end_line >= item.start_line > 0 for item in result.symbols)

    assert tuple(item.module for item in result.imports) == (
        "os",
        "package.submodule",
        ".helpers",
    )
    assert result.imports[-1].imported_names == ("alpha", "Beta")
    assert result.imports[-1].import_kind is SourceImportKind.PYTHON_FROM_IMPORT
    assert result.imports[-1].is_relative is True


def test_python_parser_marks_syntax_error_without_leaking_source() -> None:
    source = "def broken(:\n    PRIVATE_SOURCE_BODY"

    result = _parser().parse("broken.py", "Python", source)

    assert result.has_syntax_errors is True
    assert result.parse_failed is True
    assert result.symbols == ()
    assert result.imports == ()


def test_python_parser_output_is_deterministic() -> None:
    source = "from pkg import zed, Alpha\n\ndef beta():\n    pass\n\ndef Alpha():\n    pass\n"

    first = _parser().parse("module.pyi", "Python", source)
    second = _parser().parse("module.pyi", "Python", source)

    assert first == second
    assert tuple(item.name for item in first.symbols) == ("beta", "Alpha")
    assert first.imports[0].imported_names == ("Alpha", "zed")
