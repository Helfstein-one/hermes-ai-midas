"""Detector for orphan eager actions in PySpark pipelines."""

from __future__ import annotations

import ast

from hermes_midas.ast_analyzer.models import AntiPatternMatch, AntiPatternType, Severity

TARGET_ACTIONS = {
    "count",
    "collect",
    "take",
    "first",
    "head",
    "tail",
    "show",
    "toPandas",
    "describe",
    "summary",
}


class SymbolReadVisitor(ast.NodeVisitor):
    """Collects identifier read counts across an AST to detect dead assignments."""

    def __init__(self) -> None:
        self.read_counts: dict[str, int] = {}

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.read_counts[node.id] = self.read_counts.get(node.id, 0) + 1
        self.generic_visit(node)


def is_action_call(node: ast.AST) -> str | None:
    """Check if an AST node is a method call on a Spark DataFrame with a target action."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in TARGET_ACTIONS:
        return node.func.attr
    return None


def extract_action_from_print(node: ast.AST) -> tuple[str, ast.AST] | None:
    """Check if a print() call contains an eager DataFrame action call inside its arguments."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print"):
        return None

    # Check direct call arguments: print(df.count())
    for arg in node.args:
        action = is_action_call(arg)
        if action:
            return action, arg

        # Check formatted string expressions: print(f"... {df.count()} ...")
        if isinstance(arg, ast.JoinedStr):
            for value in arg.values:
                if isinstance(value, ast.FormattedValue):
                    sub_action = is_action_call(value.value)
                    if sub_action:
                        return sub_action, value.value
    return None


class OrphanActionDetector(ast.NodeVisitor):
    """Detects DataFrame actions invoked in discarded expression contexts or dead assignments."""

    def __init__(self, source_lines: list[str] | None = None) -> None:
        self.source_lines = source_lines or []
        self.matches: list[AntiPatternMatch] = []
        self._symbol_reads: dict[str, int] = {}

    def run(self, tree: ast.AST) -> list[AntiPatternMatch]:
        """Analyze the AST and return all detected orphan actions."""
        self.matches = []
        # Precompute symbol reads across the entire module
        read_visitor = SymbolReadVisitor()
        read_visitor.visit(tree)
        self._symbol_reads = read_visitor.read_counts

        self.visit(tree)
        return self.matches

    def _get_snippet(self, node: ast.AST) -> str:
        if not self.source_lines:
            return ""
        start = getattr(node, "lineno", 1) - 1
        end = getattr(node, "end_lineno", start + 1)
        if 0 <= start < len(self.source_lines):
            return "\n".join(self.source_lines[start:min(end, len(self.source_lines))]).strip()
        return ""

    def visit_Expr(self, node: ast.Expr) -> None:
        """Inspect standalone expression statements."""
        # Case A1: Direct discarded action, e.g. df.count(), df.collect(), df.show()
        action = is_action_call(node.value)
        if action:
            self.matches.append(
                AntiPatternMatch(
                    pattern_id=AntiPatternType.ORPHAN_ACTION.value,
                    pattern_name="Orphan Eager Action",
                    line_start=node.lineno,
                    line_end=getattr(node, "end_lineno", node.lineno),
                    col_offset=node.col_offset,
                    end_col_offset=getattr(node, "end_col_offset", node.col_offset),
                    severity=Severity.HIGH.value,
                    description=(
                        f"Invocation of eager DataFrame action '.{action}()' as an unassigned expression statement. "
                        "This triggers expensive cluster DAG execution and data serialization only to discard the return value."
                    ),
                    remediation_strategy=f"Remove unnecessary '.{action}()' action call.",
                    code_snippet=self._get_snippet(node),
                    action_name=action,
                    details={"action": action, "type": "standalone_expr"},
                )
            )
            return

        # Case A2: Standalone print statement wrapping an eager action
        print_action_info = extract_action_from_print(node.value)
        if print_action_info:
            p_action, _target_subnode = print_action_info
            self.matches.append(
                AntiPatternMatch(
                    pattern_id=AntiPatternType.ORPHAN_ACTION.value,
                    pattern_name="Orphan Eager Action in Print",
                    line_start=node.lineno,
                    line_end=getattr(node, "end_lineno", node.lineno),
                    col_offset=node.col_offset,
                    end_col_offset=getattr(node, "end_col_offset", node.col_offset),
                    severity=Severity.HIGH.value,
                    description=(
                        f"Eager DataFrame action '.{p_action}()' evaluated inside print(). "
                        "Triggers unnecessary full cluster scans for debugging/logging purposes."
                    ),
                    remediation_strategy=f"Remove or gate print statement containing eager '.{p_action}()'.",
                    code_snippet=self._get_snippet(node),
                    action_name=p_action,
                    details={"action": p_action, "type": "print_wrapper"},
                )
            )
            return

        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        """Inspect assignments for dead target variables."""
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target_var = node.targets[0].id
            action = is_action_call(node.value)
            if action:
                # Check downstream reads: if read count is 0 or target is dummy variable (e.g. _)
                read_count = self._symbol_reads.get(target_var, 0)
                if read_count == 0 or target_var.startswith("_"):
                    self.matches.append(
                        AntiPatternMatch(
                            pattern_id=AntiPatternType.ORPHAN_ACTION.value,
                            pattern_name="Dead Eager Action Assignment",
                            line_start=node.lineno,
                            line_end=getattr(node, "end_lineno", node.lineno),
                            col_offset=node.col_offset,
                            end_col_offset=getattr(node, "end_col_offset", node.col_offset),
                            severity=Severity.HIGH.value,
                            description=(
                                f"Eager DataFrame action '.{action}()' assigned to variable '{target_var}' "
                                f"which is never read ({read_count} references in scope)."
                            ),
                            remediation_strategy=f"Eliminate dead variable assignment '{target_var} = ...'.",
                            code_snippet=self._get_snippet(node),
                            target_variable=target_var,
                            action_name=action,
                            details={"action": action, "target_var": target_var, "type": "dead_assignment"},
                        )
                    )
                    return

        self.generic_visit(node)
