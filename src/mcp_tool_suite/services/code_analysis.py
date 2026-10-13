"""Lightweight static analysis for source code (stdlib ``ast``, no deps).

Python gets a real AST pass (structure + heuristic findings). Other languages are
handed to the LLM as-is. The static pass is what makes the reviewer more than a
prompt wrapper.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field

_MAX_LONG_LINE = 100


@dataclass(slots=True)
class Finding:
    severity: str  # "high" | "medium" | "low" | "info"
    line: int
    rule: str
    message: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class CodeReport:
    language: str
    syntax_ok: bool
    errors: list[dict[str, object]] = field(default_factory=list)
    functions: list[dict[str, object]] = field(default_factory=list)
    classes: list[dict[str, object]] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    metrics: dict[str, object] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "language": self.language,
            "syntax_ok": self.syntax_ok,
            "errors": self.errors,
            "functions": self.functions,
            "classes": self.classes,
            "imports": sorted(set(self.imports)),
            "metrics": self.metrics,
            "findings": [f.as_dict() for f in self.findings],
        }


def _is_mutable_default(node: ast.AST) -> bool:
    return isinstance(node, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp, ast.Call))


def analyze_python(code: str) -> CodeReport:
    report = CodeReport(language="python", syntax_ok=True)
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        report.syntax_ok = False
        report.errors.append({"line": exc.lineno or 0, "message": exc.msg})
        return report

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            report.functions.append(
                {
                    "name": node.name,
                    "line": node.lineno,
                    "args": len(node.args.args),
                    "is_async": isinstance(node, ast.AsyncFunctionDef),
                }
            )
            for default in node.args.defaults + [d for d in node.args.kw_defaults if d is not None]:
                if _is_mutable_default(default):
                    report.findings.append(
                        Finding("medium", node.lineno, "mutable-default", f"Function '{node.name}' uses a mutable default argument.")
                    )
        elif isinstance(node, ast.ClassDef):
            methods = sum(
                isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in node.body
            )
            report.classes.append({"name": node.name, "line": node.lineno, "methods": methods})
        elif isinstance(node, ast.Import):
            report.imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            report.imports.append(node.module or "")
            if any(alias.name == "*" for alias in node.names):
                report.findings.append(
                    Finding("low", node.lineno, "star-import", "Wildcard 'from ... import *' import.")
                )
        elif isinstance(node, ast.ExceptHandler) and node.type is None:
            report.findings.append(
                Finding("medium", getattr(node, "lineno", 0), "bare-except", "Bare 'except:' swallows all errors.")
            )
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"eval", "exec"}:
                report.findings.append(
                    Finding("high", getattr(node, "lineno", 0), "dangerous-call", f"Use of '{node.func.id}()' is a security risk.")
                )

    lines = code.splitlines()
    long_lines = [i + 1 for i, line in enumerate(lines) if len(line) > _MAX_LONG_LINE]
    todo_lines = [i + 1 for i, line in enumerate(lines) if "TODO" in line or "FIXME" in line]
    for line_no in long_lines:
        report.findings.append(Finding("low", line_no, "long-line", f"Line exceeds {_MAX_LONG_LINE} characters."))
    for line_no in todo_lines:
        report.findings.append(Finding("info", line_no, "todo", "Unresolved TODO/FIXME comment."))

    report.metrics = {
        "lines": len(lines),
        "functions": len(report.functions),
        "classes": len(report.classes),
        "findings": len(report.findings),
        "high_severity": sum(1 for f in report.findings if f.severity == "high"),
    }
    return report


def looks_like_python(code: str) -> bool:
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False
