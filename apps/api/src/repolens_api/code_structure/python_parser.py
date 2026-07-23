"""Safe Python source-structure extraction using the standard-library AST."""

import ast
from dataclasses import dataclass

from repolens_api.code_structure.contracts import (
    ImportFinding,
    ParsedSourceStructure,
    SourceImportKind,
    SourceSymbol,
    SourceSymbolKind,
)
from repolens_api.code_structure.policy import (
    MAX_MODULE_NAME_LENGTH,
    is_safe_name,
    qualified_name,
    source_import_sort_key,
    source_symbol_sort_key,
)


@dataclass(frozen=True, slots=True)
class _Scope:
    name: str
    is_class: bool


class PythonSourceParser:
    """Extract declarations and imports without importing repository modules."""

    def __init__(self, *, max_imported_names_per_import: int) -> None:
        self._max_imported_names_per_import = max_imported_names_per_import

    def parse(
        self,
        relative_path: str,
        language: str,
        source: str,
    ) -> ParsedSourceStructure:
        """Parse one Python file or return a safe syntax-error outcome."""
        try:
            tree = ast.parse(source, filename="<repository-source>", type_comments=False)
        except (SyntaxError, ValueError):
            return ParsedSourceStructure((), (), has_syntax_errors=True, parse_failed=True)

        visitor = _PythonVisitor(
            relative_path=relative_path,
            language=language,
            max_imported_names_per_import=self._max_imported_names_per_import,
        )
        visitor.visit(tree)
        return ParsedSourceStructure(
            symbols=tuple(
                sorted(
                    visitor.symbols,
                    key=lambda item: source_symbol_sort_key(
                        item.relative_path,
                        item.start_line,
                        item.qualified_name,
                        item.kind.value,
                    ),
                )
            ),
            imports=tuple(
                sorted(
                    visitor.imports,
                    key=lambda item: source_import_sort_key(
                        item.relative_path,
                        item.start_line,
                        item.module,
                        item.import_kind.value,
                    ),
                )
            ),
            has_syntax_errors=False,
            symbols_truncated=visitor.symbols_truncated,
            imports_truncated=visitor.imports_truncated,
        )


class _PythonVisitor(ast.NodeVisitor):
    def __init__(
        self,
        *,
        relative_path: str,
        language: str,
        max_imported_names_per_import: int,
    ) -> None:
        self._relative_path = relative_path
        self._language = language
        self._max_imported_names_per_import = max_imported_names_per_import
        self._scopes: list[_Scope] = []
        self.symbols: list[SourceSymbol] = []
        self.imports: list[ImportFinding] = []
        self.symbols_truncated = False
        self.imports_truncated = False

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self._record_symbol(node, SourceSymbolKind.CLASS, parameter_count=0)
        self._scopes.append(_Scope(node.name, is_class=True))
        for child in node.body:
            self.visit(child)
        self._scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        kind = (
            SourceSymbolKind.METHOD
            if self._scopes and self._scopes[-1].is_class
            else SourceSymbolKind.FUNCTION
        )
        self._record_symbol(node, kind, self._parameter_count(node.args))
        self._visit_function_body(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        kind = (
            SourceSymbolKind.ASYNC_METHOD
            if self._scopes and self._scopes[-1].is_class
            else SourceSymbolKind.ASYNC_FUNCTION
        )
        self._record_symbol(node, kind, self._parameter_count(node.args))
        self._visit_function_body(node)

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            if not is_safe_name(alias.name, maximum=MAX_MODULE_NAME_LENGTH):
                self.imports_truncated = True
                continue
            self.imports.append(
                ImportFinding(
                    relative_path=self._relative_path,
                    language=self._language,
                    module=alias.name,
                    imported_names=(),
                    import_kind=SourceImportKind.PYTHON_IMPORT,
                    is_relative=False,
                    start_line=node.lineno,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        module = f"{'.' * node.level}{node.module or ''}"
        if not is_safe_name(module, maximum=MAX_MODULE_NAME_LENGTH):
            self.imports_truncated = True
            return
        names = sorted(
            {alias.name for alias in node.names if is_safe_name(alias.name)},
            key=lambda value: (value.casefold(), value),
        )
        if len(names) != len(node.names):
            self.imports_truncated = True
        if len(names) > self._max_imported_names_per_import:
            names = names[: self._max_imported_names_per_import]
            self.imports_truncated = True
        self.imports.append(
            ImportFinding(
                relative_path=self._relative_path,
                language=self._language,
                module=module,
                imported_names=tuple(names),
                import_kind=SourceImportKind.PYTHON_FROM_IMPORT,
                is_relative=node.level > 0,
                start_line=node.lineno,
            )
        )

    def _record_symbol(
        self,
        node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
        kind: SourceSymbolKind,
        parameter_count: int,
    ) -> None:
        scope_names = tuple(scope.name for scope in self._scopes)
        qualified = qualified_name(scope_names, node.name)
        if not is_safe_name(node.name) or qualified is None:
            self.symbols_truncated = True
            return
        self.symbols.append(
            SourceSymbol(
                relative_path=self._relative_path,
                language=self._language,
                kind=kind,
                name=node.name,
                qualified_name=qualified,
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
                parent_name=self._scopes[-1].name if self._scopes else None,
                parameter_count=parameter_count,
                is_exported=False,
                is_public=not node.name.startswith("_"),
            )
        )

    def _visit_function_body(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._scopes.append(_Scope(node.name, is_class=False))
        for child in node.body:
            self.visit(child)
        self._scopes.pop()

    @staticmethod
    def _parameter_count(arguments: ast.arguments) -> int:
        return (
            len(arguments.posonlyargs)
            + len(arguments.args)
            + len(arguments.kwonlyargs)
            + (arguments.vararg is not None)
            + (arguments.kwarg is not None)
        )
