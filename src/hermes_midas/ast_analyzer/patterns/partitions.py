"""Detector for suboptimal partition operations in PySpark pipelines."""

from __future__ import annotations

import ast

from hermes_midas.ast_analyzer.models import AntiPatternMatch, AntiPatternType, Severity

TERMINAL_WRITE_ACTIONS = {
    "save",
    "parquet",
    "csv",
    "orc",
    "json",
    "text",
    "insertInto",
    "saveAsTable",
    "jdbc",
}

COMMON_PARTITION_KEYS = {
    "date",
    "dt",
    "year",
    "month",
    "day",
    "order_year",
    "order_month",
    "region",
    "tenant_id",
    "country",
}


def get_call_chain_methods(node: ast.AST) -> list[str]:
    """Traverse a method call chain and return the list of method/attribute names."""
    methods: list[str] = []
    curr = node
    while isinstance(curr, ast.Call):
        if isinstance(curr.func, ast.Attribute):
            methods.append(curr.func.attr)
            curr = curr.func.value
        else:
            break
    while isinstance(curr, ast.Attribute):
        methods.append(curr.attr)
        curr = curr.value
    return methods


def find_inferred_partition_keys(source_text: str) -> list[str]:
    """Find plausible partition keys referenced in the source text."""
    lower_text = source_text.lower()
    keys: list[str] = []
    if "order_year" in lower_text and "order_month" in lower_text:
        return ["order_year", "order_month"]
    if "year" in lower_text and "month" in lower_text:
        return ["year", "month"]
    for key in ["date", "dt", "region", "tenant_id", "country"]:
        if f'"{key}"' in lower_text or f"'{key}'" in lower_text:
            keys.append(key)
    return keys or ["date"]


class SuboptimalPartitionDetector(ast.NodeVisitor):
    """Detects excessive repartitioning, hazardous coalesce(1), and missing partitionBy on writes."""

    def __init__(self, source_lines: list[str] | None = None, raw_source: str = "") -> None:
        self.source_lines = source_lines or []
        self.raw_source = raw_source or ("\n".join(self.source_lines) if self.source_lines else "")
        self.matches: list[AntiPatternMatch] = []

    def run(self, tree: ast.AST) -> list[AntiPatternMatch]:
        """Analyze the AST and return all detected partition anti-patterns."""
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
        """Inspect calls for repartition, coalesce, and write chains."""
        if isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr

            # Case A: Excessive repartitioning without column expressions
            if attr_name == "repartition":
                # Only flag if there is a single constant integer argument > 200 without column args
                if (
                    len(node.args) == 1
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, int)
                ):
                    partition_count = node.args[0].value
                    if partition_count > 200:
                        self.matches.append(
                            AntiPatternMatch(
                                pattern_id=AntiPatternType.SUBOPTIMAL_PARTITION.value,
                                pattern_name="Excessive Repartitioning",
                                line_start=node.lineno,
                                line_end=getattr(node, "end_lineno", node.lineno),
                                col_offset=node.col_offset,
                                end_col_offset=getattr(node, "end_col_offset", node.col_offset),
                                severity=Severity.HIGH.value,
                                description=(
                                    f"Explicit repartition({partition_count}) creates excessive micro-partitions. "
                                    "Forces a full cluster network shuffle and triggers high executor scheduling overhead and small file proliferation."
                                ),
                                remediation_strategy=f"Replace repartition({partition_count}) with coalesce(64) or scale to 128MB per partition.",
                                code_snippet=self._get_snippet(node),
                                details={"partition_count": partition_count, "type": "excessive_repartition"},
                            )
                        )

            # Case B: Hazardous coalesce(1) on datasets
            elif attr_name == "coalesce":
                if len(node.args) == 1 and isinstance(node.args[0], ast.Constant) and node.args[0].value == 1:
                    self.matches.append(
                        AntiPatternMatch(
                            pattern_id=AntiPatternType.SUBOPTIMAL_PARTITION.value,
                            pattern_name="Hazardous Coalesce(1)",
                            line_start=node.lineno,
                            line_end=getattr(node, "end_lineno", node.lineno),
                            col_offset=node.col_offset,
                            end_col_offset=getattr(node, "end_col_offset", node.col_offset),
                            severity=Severity.CRITICAL.value,
                            description=(
                                "Invocation of coalesce(1) collapses all partition processing to a single executor core. "
                                "This creates an extreme cluster bottleneck and frequently triggers driver / worker Out-Of-Memory (OOM) crashes."
                            ),
                            remediation_strategy="Replace coalesce(1) with coalesce(min_partitions) or right-sized target partitions.",
                            code_snippet=self._get_snippet(node),
                            details={"partition_count": 1, "type": "coalesce_one"},
                        )
                    )

            # Case C: Missing partitionBy on DataFrame writes
            elif attr_name in TERMINAL_WRITE_ACTIONS:
                chain = get_call_chain_methods(node)
                # Check if 'write' is in the chain and 'partitionBy' is missing
                if "write" in chain and "partitionBy" not in chain:
                    suggested_keys = find_inferred_partition_keys(self.raw_source)
                    self.matches.append(
                        AntiPatternMatch(
                            pattern_id=AntiPatternType.SUBOPTIMAL_PARTITION.value,
                            pattern_name="Missing PartitionBy on Write",
                            line_start=node.lineno,
                            line_end=getattr(node, "end_lineno", node.lineno),
                            col_offset=node.col_offset,
                            end_col_offset=getattr(node, "end_col_offset", node.col_offset),
                            severity=Severity.MEDIUM.value,
                            description=(
                                f"DataFrame write sink '.{attr_name}()' executed without .partitionBy(...). "
                                "Writing unpartitioned datasets harms downstream scan performance and partition pruning."
                            ),
                            remediation_strategy=f"Add .partitionBy({', '.join(repr(k) for k in suggested_keys)}) prior to .{attr_name}().",
                            code_snippet=self._get_snippet(node),
                            details={
                                "write_action": attr_name,
                                "suggested_keys": suggested_keys,
                                "type": "missing_partition_by",
                            },
                        )
                    )

        self.generic_visit(node)
