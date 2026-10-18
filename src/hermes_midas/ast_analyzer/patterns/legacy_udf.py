"""Detector for legacy row-by-row Python UDFs in PySpark pipelines."""

from __future__ import annotations

import ast

from hermes_midas.ast_analyzer.models import AntiPatternMatch, AntiPatternType, Severity


def is_udf_decorator(decorator: ast.AST) -> bool:
    """Check if a decorator is @udf or @F.udf (with or without call arguments)."""
    # Case 1: @udf
    if isinstance(decorator, ast.Name) and decorator.id == "udf":
        return True
    # Case 2: @F.udf or @functions.udf
    if isinstance(decorator, ast.Attribute) and decorator.attr == "udf":
        return True
    # Case 3: @udf(...) or @F.udf(...)
    if isinstance(decorator, ast.Call):
        return is_udf_decorator(decorator.func)
    return False


def is_pure_sql_expressible(func_node: ast.FunctionDef) -> bool:
    """Check if a function's body consists of simple string transforms, null coalescing, or simple math."""
    # If function contains loops, it is complex
    for subnode in ast.walk(func_node):
        if isinstance(subnode, (ast.For, ast.While, ast.AsyncFor)):
            return False
        # Check for numpy, scipy, or math calls
        if isinstance(subnode, ast.Attribute) and subnode.attr in {"sin", "cos", "exp", "dot", "matrix"}:
            return False

    # Check if statements are simple returns / ifs with string ops or basic arithmetic
    returns = [n for n in ast.walk(func_node) if isinstance(n, ast.Return)]
    if not returns:
        return False

    for ret in returns:
        if ret.value is None:
            continue
        # String methods or formatting
        if isinstance(ret.value, (ast.JoinedStr, ast.BinOp)):
            return True
        if (
            isinstance(ret.value, ast.Call)
            and isinstance(ret.value.func, ast.Attribute)
            and ret.value.func.attr in {"upper", "lower", "strip", "lstrip", "rstrip", "replace", "split"}
        ):
            return True
        if isinstance(ret.value, ast.Constant) and isinstance(ret.value.value, (str, int, float)):
            return True

    return False


class LegacyUdfDetector(ast.NodeVisitor):
    """Detects standard Python @udf decorators that should be converted to native SQL or pandas_udf."""

    def __init__(self, source_lines: list[str] | None = None) -> None:
        self.source_lines = source_lines or []
        self.matches: list[AntiPatternMatch] = []

    def run(self, tree: ast.AST) -> list[AntiPatternMatch]:
        """Analyze the AST and return all detected legacy UDF anti-patterns."""
        self.matches = []
        self.visit(tree)
        return self.matches

    def _get_snippet(self, node: ast.AST) -> str:
        if not self.source_lines:
            return ""
        start = getattr(node, "lineno", 1) - 1
        end = getattr(node, "end_lineno", start + 1)
        if 0 <= start < len(self.source_lines):
            return "\n".join(self.source_lines[start : min(end, len(self.source_lines))]).strip()
        return ""

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Inspect function definitions for @udf decorators."""
        udf_decorator = next((d for d in node.decorator_list if is_udf_decorator(d)), None)
        if udf_decorator:
            func_name = node.name
            is_simple = is_pure_sql_expressible(node)
            sub_category = "sql_expressible" if is_simple else "complex_vectorizable"

            if is_simple:
                desc = (
                    f"Legacy row-by-row Python @udf '{func_name}' detected. Its logic is expressible using "
                    "native PySpark Catalyst expressions (e.g., F.upper, F.coalesce, F.concat_ws, F.when), "
                    "which eliminates JVM-Python socket IPC serialization bottlenecks."
                )
                remediation = (
                    f"Replace '@udf def {func_name}' with native PySpark functions (e.g. F.upper, F.concat_ws, F.when)."
                )
            else:
                desc = (
                    f"Legacy row-by-row Python @udf '{func_name}' detected. For complex calculations, "
                    "standard Python UDFs suffer severe serialization overhead. Converting to @pandas_udf "
                    "enables Apache Arrow zero-copy vectorized processing."
                )
                remediation = f"Convert '@udf def {func_name}' to '@pandas_udf' with pandas Series type hints."

            self.matches.append(
                AntiPatternMatch(
                    pattern_id=AntiPatternType.LEGACY_UDF.value,
                    pattern_name="Legacy Python Row-by-Row UDF",
                    line_start=node.lineno,
                    line_end=getattr(node, "end_lineno", node.lineno),
                    col_offset=node.col_offset,
                    end_col_offset=getattr(node, "end_col_offset", node.col_offset),
                    severity=Severity.HIGH.value,
                    description=desc,
                    remediation_strategy=remediation,
                    code_snippet=self._get_snippet(node),
                    target_variable=func_name,
                    details={"function_name": func_name, "sub_category": sub_category},
                )
            )

        self.generic_visit(node)
