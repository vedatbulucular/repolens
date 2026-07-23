"""Tree-sitter structure extraction for JavaScript and TypeScript."""

import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

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

JAVASCRIPT_LANGUAGE = Language(tree_sitter_javascript.language())
TYPESCRIPT_LANGUAGE = Language(tree_sitter_typescript.language_typescript())
TSX_LANGUAGE = Language(tree_sitter_typescript.language_tsx())
IDENTIFIER_NODE_TYPES = frozenset(
    {
        "identifier",
        "private_property_identifier",
        "property_identifier",
        "type_identifier",
    }
)


class JavaScriptSourceParser:
    """Extract supported ECMAScript declarations without evaluating code."""

    def __init__(self, *, max_imported_names_per_import: int) -> None:
        self._max_imported_names_per_import = max_imported_names_per_import

    def parse(
        self,
        relative_path: str,
        language: str,
        source: str,
    ) -> ParsedSourceStructure:
        """Parse JavaScript, JSX, TypeScript, or TSX with its fixed grammar."""
        source_bytes = source.encode("utf-8", errors="strict")
        parser = Parser(self._language_for(relative_path))
        tree = parser.parse(source_bytes)
        extractor = _JavaScriptExtractor(
            relative_path=relative_path,
            language=language,
            source=source_bytes,
            max_imported_names_per_import=self._max_imported_names_per_import,
        )
        extractor.extract(tree.root_node)
        return ParsedSourceStructure(
            symbols=tuple(
                sorted(
                    extractor.symbols,
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
                    extractor.imports,
                    key=lambda item: source_import_sort_key(
                        item.relative_path,
                        item.start_line,
                        item.module,
                        item.import_kind.value,
                    ),
                )
            ),
            has_syntax_errors=tree.root_node.has_error,
            symbols_truncated=extractor.symbols_truncated,
            imports_truncated=extractor.imports_truncated,
        )

    @staticmethod
    def _language_for(relative_path: str) -> Language:
        folded = relative_path.casefold()
        if folded.endswith(".tsx"):
            return TSX_LANGUAGE
        if folded.endswith((".ts", ".mts", ".cts")):
            return TYPESCRIPT_LANGUAGE
        return JAVASCRIPT_LANGUAGE


class _JavaScriptExtractor:
    def __init__(
        self,
        *,
        relative_path: str,
        language: str,
        source: bytes,
        max_imported_names_per_import: int,
    ) -> None:
        self._relative_path = relative_path
        self._language = language
        self._source = source
        self._max_imported_names_per_import = max_imported_names_per_import
        self._exported_names: set[str] = set()
        self.symbols: list[SourceSymbol] = []
        self.imports: list[ImportFinding] = []
        self.symbols_truncated = False
        self.imports_truncated = False

    def extract(self, root: Node) -> None:
        self._collect_exported_names(root)
        self._walk(root, scope=(), inside_class=False)

    def _walk(self, node: Node, *, scope: tuple[str, ...], inside_class: bool) -> None:
        if node.type == "import_statement":
            self._record_import_statement(node)
            return
        if node.type == "call_expression":
            self._record_require_call(node)
        if node.type == "class_declaration":
            name = self._identifier_text(node.child_by_field_name("name"))
            if name is None:
                self.symbols_truncated = True
                return
            self._record_symbol(
                node,
                name=name,
                kind=SourceSymbolKind.CLASS,
                scope=scope,
                parameter_count=0,
            )
            body = node.child_by_field_name("body")
            if body is not None:
                self._walk(body, scope=(*scope, name), inside_class=True)
            return
        if node.type == "method_definition" and inside_class:
            name = self._identifier_text(node.child_by_field_name("name"))
            if name is None:
                self.symbols_truncated = True
                return
            kind = (
                SourceSymbolKind.ASYNC_METHOD if self._is_async(node) else SourceSymbolKind.METHOD
            )
            self._record_symbol(
                node,
                name=name,
                kind=kind,
                scope=scope,
                parameter_count=self._parameter_count(node),
            )
            body = node.child_by_field_name("body")
            if body is not None:
                self._walk(body, scope=(*scope, name), inside_class=False)
            return
        if node.type == "function_declaration":
            name = self._identifier_text(node.child_by_field_name("name"))
            if name is None:
                return
            kind = (
                SourceSymbolKind.ASYNC_FUNCTION
                if self._is_async(node)
                else SourceSymbolKind.FUNCTION
            )
            self._record_symbol(
                node,
                name=name,
                kind=kind,
                scope=scope,
                parameter_count=self._parameter_count(node),
            )
            body = node.child_by_field_name("body")
            if body is not None:
                self._walk(body, scope=(*scope, name), inside_class=False)
            return
        if node.type == "variable_declarator":
            value = node.child_by_field_name("value")
            if value is not None and value.type in {"arrow_function", "function_expression"}:
                name = self._identifier_text(node.child_by_field_name("name"))
                if name is None:
                    return
                kind = (
                    SourceSymbolKind.ASYNC_FUNCTION
                    if self._is_async(value)
                    else SourceSymbolKind.FUNCTION
                )
                self._record_symbol(
                    node,
                    name=name,
                    kind=kind,
                    scope=scope,
                    parameter_count=self._parameter_count(value),
                    line_node=value,
                )
                body = value.child_by_field_name("body")
                if body is not None:
                    self._walk(body, scope=(*scope, name), inside_class=False)
                return

        for child in node.named_children:
            self._walk(child, scope=scope, inside_class=inside_class)

    def _record_symbol(
        self,
        node: Node,
        *,
        name: str,
        kind: SourceSymbolKind,
        scope: tuple[str, ...],
        parameter_count: int,
        line_node: Node | None = None,
    ) -> None:
        qualified = qualified_name(scope, name)
        if not is_safe_name(name) or qualified is None:
            self.symbols_truncated = True
            return
        location = line_node or node
        self.symbols.append(
            SourceSymbol(
                relative_path=self._relative_path,
                language=self._language,
                kind=kind,
                name=name,
                qualified_name=qualified,
                start_line=location.start_point.row + 1,
                end_line=location.end_point.row + 1,
                parent_name=scope[-1] if scope else None,
                parameter_count=parameter_count,
                is_exported=name in self._exported_names,
                is_public=not name.startswith(("_", "#")),
            )
        )

    def _record_import_statement(self, node: Node) -> None:
        source_node = node.child_by_field_name("source")
        module = self._string_literal(source_node)
        if module is None:
            self.imports_truncated = True
            return

        names: list[str] = []
        clause = next(
            (child for child in node.named_children if child.type == "import_clause"),
            None,
        )
        if clause is not None:
            for child in clause.named_children:
                if child.type == "identifier":
                    names.append("default")
                elif child.type == "namespace_import":
                    names.append("*")
                elif child.type == "named_imports":
                    for specifier in child.named_children:
                        imported = self._identifier_text(specifier.child_by_field_name("name"))
                        if imported is not None:
                            names.append(imported)

        imported_names = self._bounded_names(names)
        self.imports.append(
            ImportFinding(
                relative_path=self._relative_path,
                language=self._language,
                module=module,
                imported_names=imported_names,
                import_kind=SourceImportKind.ECMASCRIPT_IMPORT,
                is_relative=module.startswith(("./", "../")),
                start_line=node.start_point.row + 1,
            )
        )

    def _record_require_call(self, node: Node) -> None:
        function = self._identifier_text(node.child_by_field_name("function"))
        arguments = node.child_by_field_name("arguments")
        if function != "require" or arguments is None or len(arguments.named_children) != 1:
            return
        module = self._string_literal(arguments.named_children[0])
        if module is None:
            return
        self.imports.append(
            ImportFinding(
                relative_path=self._relative_path,
                language=self._language,
                module=module,
                imported_names=(),
                import_kind=SourceImportKind.COMMONJS_REQUIRE,
                is_relative=module.startswith(("./", "../")),
                start_line=node.start_point.row + 1,
            )
        )

    def _collect_exported_names(self, root: Node) -> None:
        pending = [root]
        while pending:
            node = pending.pop()
            if node.type == "export_statement":
                declaration = node.child_by_field_name("declaration")
                if declaration is not None:
                    name = self._identifier_text(declaration.child_by_field_name("name"))
                    if name is not None:
                        self._exported_names.add(name)
                    if declaration.type in {"lexical_declaration", "variable_declaration"}:
                        for declarator in declaration.named_children:
                            if declarator.type != "variable_declarator":
                                continue
                            declared_name = self._identifier_text(
                                declarator.child_by_field_name("name")
                            )
                            if declared_name is not None:
                                self._exported_names.add(declared_name)
                value = node.child_by_field_name("value")
                if value is not None:
                    name = self._identifier_text(value)
                    if name is not None:
                        self._exported_names.add(name)
                for child in node.named_children:
                    if child.type != "export_clause":
                        continue
                    for specifier in child.named_children:
                        name = self._identifier_text(specifier.child_by_field_name("name"))
                        if name is not None:
                            self._exported_names.add(name)
            pending.extend(reversed(node.named_children))

    def _bounded_names(self, names: list[str]) -> tuple[str, ...]:
        safe_names = sorted(
            {name for name in names if is_safe_name(name)},
            key=lambda value: (value.casefold(), value),
        )
        if len(safe_names) != len(names):
            self.imports_truncated = True
        if len(safe_names) > self._max_imported_names_per_import:
            safe_names = safe_names[: self._max_imported_names_per_import]
            self.imports_truncated = True
        return tuple(safe_names)

    def _string_literal(self, node: Node | None) -> str | None:
        value = self._node_text(node)
        if value is None or len(value) < 2 or value[0] not in {"'", '"'} or value[-1] != value[0]:
            return None
        module = value[1:-1]
        if "\\" in module or not is_safe_name(module, maximum=MAX_MODULE_NAME_LENGTH):
            return None
        return module

    def _node_text(self, node: Node | None) -> str | None:
        if node is None:
            return None
        try:
            value = self._source[node.start_byte : node.end_byte].decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None
        return value if is_safe_name(value, maximum=MAX_MODULE_NAME_LENGTH) else None

    def _identifier_text(self, node: Node | None) -> str | None:
        if node is None or node.type not in IDENTIFIER_NODE_TYPES:
            return None
        return self._node_text(node)

    @staticmethod
    def _is_async(node: Node) -> bool:
        return any(child.type == "async" for child in node.children)

    @staticmethod
    def _parameter_count(node: Node) -> int:
        parameters = node.child_by_field_name("parameters")
        if parameters is None:
            parameter = node.child_by_field_name("parameter")
            return 1 if parameter is not None else 0
        if parameters.type != "formal_parameters":
            return 1
        return len(parameters.named_children)
