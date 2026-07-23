"""Tests for Tree-sitter JavaScript and TypeScript structure extraction."""

import pytest

from repolens_api.code_structure.contracts import (
    SourceImportKind,
    SourceSymbolKind,
)
from repolens_api.code_structure.javascript_parser import JavaScriptSourceParser


def _parser() -> JavaScriptSourceParser:
    return JavaScriptSourceParser(max_imported_names_per_import=10)


@pytest.mark.parametrize(
    ("relative_path", "language"),
    [
        ("src/module.js", "JavaScript"),
        ("src/module.mjs", "JavaScript"),
        ("src/module.cjs", "JavaScript"),
        ("src/module.ts", "TypeScript"),
        ("src/module.mts", "TypeScript"),
        ("src/module.cts", "TypeScript"),
    ],
)
def test_javascript_parser_extracts_functions_classes_exports_and_imports(
    relative_path: str,
    language: str,
) -> None:
    type_annotation = ": number" if language == "TypeScript" else ""
    source = f"""// function fake() {{}}
const text = "class Fake {{ method() {{}} }}";
import defaultValue, {{ beta as renamed, Alpha }} from "package";
import * as namespace from "./relative";
export async function run(first{type_annotation}, second{type_annotation}) {{
  function nested(value{type_annotation}) {{ return value; }}
}}
export class Demo {{
  async method(value{type_annotation}) {{ return value; }}
  _private() {{}}
}}
const arrow = async (value{type_annotation}) => value;
const expression = function(value{type_annotation}) {{ return value; }};
export {{ arrow as publicArrow }};
export default expression;
const required = require("required-package");
"""

    result = _parser().parse(relative_path, language, source)

    assert result.has_syntax_errors is False
    assert tuple(item.name for item in result.symbols) == (
        "run",
        "nested",
        "Demo",
        "method",
        "_private",
        "arrow",
        "expression",
    )
    assert tuple(item.qualified_name for item in result.symbols) == (
        "run",
        "run.nested",
        "Demo",
        "Demo.method",
        "Demo._private",
        "arrow",
        "expression",
    )
    assert tuple(item.kind for item in result.symbols) == (
        SourceSymbolKind.ASYNC_FUNCTION,
        SourceSymbolKind.FUNCTION,
        SourceSymbolKind.CLASS,
        SourceSymbolKind.ASYNC_METHOD,
        SourceSymbolKind.METHOD,
        SourceSymbolKind.ASYNC_FUNCTION,
        SourceSymbolKind.FUNCTION,
    )
    assert tuple(item.is_exported for item in result.symbols) == (
        True,
        False,
        True,
        False,
        False,
        True,
        True,
    )
    assert result.symbols[4].is_public is False
    assert result.symbols[0].parameter_count == 2
    assert result.symbols[3].parent_name == "Demo"

    assert tuple(item.module for item in result.imports) == (
        "package",
        "./relative",
        "required-package",
    )
    assert result.imports[0].imported_names == ("Alpha", "beta", "default")
    assert result.imports[0].import_kind is SourceImportKind.ECMASCRIPT_IMPORT
    assert result.imports[1].is_relative is True
    assert result.imports[2].import_kind is SourceImportKind.COMMONJS_REQUIRE


@pytest.mark.parametrize(
    ("relative_path", "language", "source"),
    [
        (
            "component.jsx",
            "JavaScript",
            "export function Component() { return <main>Hello</main>; }",
        ),
        (
            "component.tsx",
            "TypeScript",
            "export function Component(): JSX.Element { return <main>Hello</main>; }",
        ),
    ],
)
def test_jsx_and_tsx_are_parsed_with_their_supported_grammars(
    relative_path: str,
    language: str,
    source: str,
) -> None:
    result = _parser().parse(relative_path, language, source)

    assert result.has_syntax_errors is False
    assert tuple(item.name for item in result.symbols) == ("Component",)
    assert result.symbols[0].is_exported is True


def test_tree_sitter_error_nodes_allow_safe_partial_structure() -> None:
    source = "export function valid() {}\nfunction broken( {\nconst retained = () => 1;"

    result = _parser().parse("broken.ts", "TypeScript", source)

    assert result.has_syntax_errors is True
    assert "valid" in {item.name for item in result.symbols}
    assert all("PRIVATE_SOURCE_BODY" not in item.name for item in result.symbols)


def test_computed_and_destructured_names_cannot_leak_source_snippets() -> None:
    source = """
const {leaked} = () => PRIVATE_SOURCE_BODY;
class Demo {
  [PRIVATE_SOURCE_BODY()]() {}
  safe() {}
}
"""

    result = _parser().parse("module.js", "JavaScript", source)

    assert tuple(item.name for item in result.symbols) == ("Demo", "safe")
    assert "PRIVATE_SOURCE_BODY" not in repr(result)


def test_javascript_parser_output_is_deterministic() -> None:
    source = 'const second = () => 2;\nconst first = () => 1;\nrequire("module");'

    first = _parser().parse("index.js", "JavaScript", source)
    second = _parser().parse("index.js", "JavaScript", source)

    assert first == second
    assert tuple(item.name for item in first.symbols) == ("second", "first")
