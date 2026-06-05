from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.app.codeintel.language import detect_language
from backend.app.core.redaction import redact_text


@dataclass(slots=True)
class ParsedSymbol:
    name: str
    kind: str
    language: str | None
    start_line: int
    end_line: int | None = None
    signature: str | None = None
    docstring: str | None = None
    parent_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedReference:
    reference_name: str
    reference_type: str
    line: int
    column: int | None = None
    snippet: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParseResult:
    language: str | None
    symbols: list[ParsedSymbol] = field(default_factory=list)
    references: list[ParsedReference] = field(default_factory=list)


TS_CLASS_RE = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)")
TS_FUNCTION_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)"
)
TS_CONST_FUNCTION_RE = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>"
)
TS_IMPORT_RE = re.compile(r"^\s*import\s+(?:.+?\s+from\s+)?['\"]([^'\"]+)['\"]")
TS_EXPORT_FROM_RE = re.compile(r"^\s*export\s+.+?\s+from\s+['\"]([^'\"]+)['\"]")
TS_CALL_RE = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\(")
MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def parse_code(path: str | Path, content: str, language: str | None = None) -> ParseResult:
    lang = language or detect_language(path)
    if lang == "python":
        return parse_python(content)
    if lang in {"typescript", "javascript"}:
        return parse_typescript_like(content, language=lang)
    if lang == "markdown":
        return parse_markdown(content)
    return ParseResult(language=lang)


def parse_python(content: str) -> ParseResult:
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        return ParseResult(
            language="python",
            references=[
                ParsedReference(
                    reference_name="syntax_error",
                    reference_type="unknown",
                    line=exc.lineno or 1,
                    column=exc.offset,
                    snippet=redact_text(exc.text or ""),
                    metadata={"message": exc.msg},
                )
            ],
        )
    lines = content.splitlines()
    symbols: list[ParsedSymbol] = []
    references: list[ParsedReference] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.parents: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> Any:
            symbols.append(
                ParsedSymbol(
                    name=node.name,
                    kind="class",
                    language="python",
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", None),
                    signature=f"class {node.name}",
                    docstring=ast.get_docstring(node),
                    parent_name=self.parents[-1] if self.parents else None,
                )
            )
            references.append(_definition_reference(node.name, node.lineno, lines))
            self.parents.append(node.name)
            self.generic_visit(node)
            self.parents.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
            self._function(node, async_prefix=False)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
            self._function(node, async_prefix=True)

        def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, *, async_prefix: bool) -> None:
            args = ", ".join(arg.arg for arg in node.args.args)
            kind = "method" if self.parents else "function"
            prefix = "async " if async_prefix else ""
            symbols.append(
                ParsedSymbol(
                    name=node.name,
                    kind=kind,
                    language="python",
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", None),
                    signature=f"{prefix}def {node.name}({args})",
                    docstring=ast.get_docstring(node),
                    parent_name=self.parents[-1] if self.parents else None,
                )
            )
            references.append(_definition_reference(node.name, node.lineno, lines))
            self.parents.append(node.name)
            self.generic_visit(node)
            self.parents.pop()

        def visit_Assign(self, node: ast.Assign) -> Any:
            if self.parents:
                self.generic_visit(node)
                return
            for target in node.targets:
                if isinstance(target, ast.Name):
                    symbols.append(
                        ParsedSymbol(
                            name=target.id,
                            kind="variable",
                            language="python",
                            start_line=node.lineno,
                            end_line=getattr(node, "end_lineno", None),
                            signature=target.id,
                        )
                    )
                    references.append(_definition_reference(target.id, node.lineno, lines))
            self.generic_visit(node)

        def visit_Import(self, node: ast.Import) -> Any:
            for alias in node.names:
                references.append(_reference(alias.name, "import", node.lineno, node.col_offset, lines))

        def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
            module = node.module or ""
            for alias in node.names:
                name = f"{module}.{alias.name}" if module else alias.name
                references.append(_reference(name, "import", node.lineno, node.col_offset, lines))

        def visit_Call(self, node: ast.Call) -> Any:
            name = _call_name(node.func)
            if name:
                references.append(_reference(name, "call", node.lineno, node.col_offset, lines))
            self.generic_visit(node)

    Visitor().visit(tree)
    return ParseResult(language="python", symbols=symbols, references=references)


def parse_typescript_like(content: str, *, language: str) -> ParseResult:
    symbols: list[ParsedSymbol] = []
    references: list[ParsedReference] = []
    lines = content.splitlines()
    for index, line in enumerate(lines, start=1):
        class_match = TS_CLASS_RE.match(line)
        if class_match:
            name = class_match.group(1)
            symbols.append(ParsedSymbol(name=name, kind="class", language=language, start_line=index, signature=line.strip()))
            references.append(_definition_reference(name, index, lines))
            continue
        function_match = TS_FUNCTION_RE.match(line)
        if function_match:
            name = function_match.group(1)
            symbols.append(ParsedSymbol(name=name, kind="function", language=language, start_line=index, signature=line.strip()))
            references.append(_definition_reference(name, index, lines))
            continue
        const_match = TS_CONST_FUNCTION_RE.match(line)
        if const_match:
            name = const_match.group(1)
            symbols.append(ParsedSymbol(name=name, kind="function", language=language, start_line=index, signature=line.strip()))
            references.append(_definition_reference(name, index, lines))
        import_match = TS_IMPORT_RE.match(line) or TS_EXPORT_FROM_RE.match(line)
        if import_match:
            references.append(_reference(import_match.group(1), "import", index, line.find(import_match.group(1)) + 1, lines))
        for call in TS_CALL_RE.finditer(line):
            references.append(_reference(call.group(1), "call", index, call.start(1) + 1, lines))
    return ParseResult(language=language, symbols=symbols, references=references)


def parse_markdown(content: str) -> ParseResult:
    symbols: list[ParsedSymbol] = []
    lines = content.splitlines()
    for index, line in enumerate(lines, start=1):
        match = MD_HEADING_RE.match(line)
        if not match:
            continue
        symbols.append(
            ParsedSymbol(
                name=match.group(2).strip(),
                kind="module",
                language="markdown",
                start_line=index,
                signature=line.strip(),
                metadata={"level": len(match.group(1))},
            )
        )
    return ParseResult(language="markdown", symbols=symbols, references=[])


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _definition_reference(name: str, line: int, lines: list[str]) -> ParsedReference:
    return _reference(name, "definition", line, None, lines)


def _reference(name: str, reference_type: str, line: int, column: int | None, lines: list[str]) -> ParsedReference:
    snippet = lines[line - 1].strip() if 0 <= line - 1 < len(lines) else None
    return ParsedReference(
        reference_name=name,
        reference_type=reference_type,
        line=line,
        column=column,
        snippet=redact_text(snippet or "") if snippet else None,
    )
