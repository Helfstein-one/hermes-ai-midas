"""Detector for unbroadcasted dimension table joins in PySpark pipelines."""

from __future__ import annotations

import ast

from hermes_midas.ast_analyzer.models import AntiPatternMatch, AntiPatternType, Severity

DIMENSION_PREFIXES = ("dim_", "lookup_", "ref_", "meta_", "code_")
DIMENSION_SUFFIXES = ("_dim", "_lookup", "_ref", "_mapping", "_metadata", "_codes", "_table")
KNOWN_DIMENSION_NAMES = {
    "dim_campaigns",
    "dim_geographic_codes",
    "dim_users",
    "dim_customers",
    "campaign_df",
    "campaigns",
    "geo_lookup",
    "zip_codes",
}


def is_already_broadcasted(node: ast.AST) -> bool:
    """Check if a join argument is already wrapped with broadcast(...) or F.broadcast(...)."""
    if isinstance(node, ast.Call):
        # Case 1: broadcast(df)
        if isinstance(node.func, ast.Name) and node.func.id == "broadcast":
            return True
        # Case 2: F.broadcast(df) or functions.broadcast(df)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "broadcast":
            return True
    return False


def is_dimension_identifier(name: str) -> bool:
    """Heuristic check to determine if an identifier name corresponds to a small dimension table."""
    lower_name = name.lower()
    if lower_name in KNOWN_DIMENSION_NAMES:
        return True
    if lower_name.startswith(DIMENSION_PREFIXES):
        return True
    if lower_name.endswith(DIMENSION_SUFFIXES):
        return True
    return any(token in lower_name for token in ["dim_", "_dim", "lookup", "campaign"])


def extract_right_df_name(node: ast.AST) -> str | None:
    """Extract identifier or table name from the right-hand dataset node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    # Calls like spark.table("dim_xyz") or spark.read.parquet("...dim_xyz...")
    if isinstance(node, ast.Call):
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                val = arg.value.lower()
                if is_dimension_identifier(val) or any(p in val for p in ["dim_", "lookup"]):
                    return arg.value
    return None


class UnbroadcastedJoinDetector(ast.NodeVisitor):
    """Identifies bare dimension table joins lacking broadcast hints."""

    def __init__(
        self,
        source_lines: list[str] | None = None,
        custom_dimensions: set[str] | None = None,
    ) -> None:
        self.source_lines = source_lines or []
        self.custom_dimensions = custom_dimensions or set()
        self.matches: list[AntiPatternMatch] = []

    def run(self, tree: ast.AST) -> list[AntiPatternMatch]:
        """Analyze the AST and return all detected unbroadcasted joins."""
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

    def visit_Call(self, node: ast.Call) -> None:
        """Inspect method calls for .join(...) operations."""
        if isinstance(node.func, ast.Attribute) and node.func.attr == "join" and len(node.args) >= 1:
            right_df = node.args[0]
            # Check if already broadcasted
            if not is_already_broadcasted(right_df):
                right_name = extract_right_df_name(right_df)
                is_dim = False
                if right_name and (right_name in self.custom_dimensions or is_dimension_identifier(right_name)):
                    is_dim = True

                    if is_dim:
                        dim_label = right_name or "dimension_table"
                        self.matches.append(
                            AntiPatternMatch(
                                pattern_id=AntiPatternType.UNBROADCASTED_JOIN.value,
                                pattern_name="Unbroadcasted Dimension Join",
                                line_start=node.lineno,
                                line_end=getattr(node, "end_lineno", node.lineno),
                                col_offset=node.col_offset,
                                end_col_offset=getattr(node, "end_col_offset", node.col_offset),
                                severity=Severity.CRITICAL.value,
                                description=(
                                    f"Join with dimension dataset '{dim_label}' lacks a broadcast hint. "
                                    "Without broadcast(F.broadcast), Spark defaults to SortMergeJoin or ShuffleHashJoin, "
                                    "inducing heavy network shuffle and disk spill."
                                ),
                                remediation_strategy=f"Wrap right-hand table '{dim_label}' in F.broadcast().",
                                code_snippet=self._get_snippet(node),
                                target_variable=dim_label,
                                details={"right_df": dim_label, "node": right_df},
                            )
                        )

        self.generic_visit(node)
