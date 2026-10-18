"""Deterministic AST patch generator for PySpark pipelines."""

from __future__ import annotations

import ast
import difflib

from hermes_midas.ast_analyzer.patterns.legacy_udf import (
    is_udf_decorator,
)
from hermes_midas.ast_analyzer.patterns.orphan_actions import (
    extract_action_from_print,
    is_action_call,
)
from hermes_midas.ast_analyzer.patterns.partitions import (
    TERMINAL_WRITE_ACTIONS,
    find_inferred_partition_keys,
    get_call_chain_methods,
)
from hermes_midas.ast_analyzer.patterns.unbroadcasted_joins import (
    is_already_broadcasted,
    is_dimension_identifier,
)


def has_pyspark_functions_import(tree: ast.AST) -> bool:
    """Check if pyspark.sql.functions is imported as F or functions."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "pyspark.sql.functions" and alias.asname in {"F", "functions"}:
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == "pyspark.sql" and any(
                alias.name == "functions" and alias.asname == "F" for alias in node.names
            ):
                return True
            if node.module == "pyspark.sql.functions" and any(alias.name == "broadcast" for alias in node.names):
                return True
    return False


def create_f_import_node() -> ast.Import:
    """Create an 'import pyspark.sql.functions as F' AST node."""
    return ast.Import(names=[ast.alias(name="pyspark.sql.functions", asname="F")])


class AstTransformer(ast.NodeTransformer):
    """Transforms PySpark AST to remediate detected compute anti-patterns."""

    def __init__(self, raw_source: str = "") -> None:
        super().__init__()
        self.raw_source = raw_source
        self.has_modified = False
        self.injected_broadcast = False
        self.inferred_partition_keys = find_inferred_partition_keys(raw_source)

    def visit_Expr(self, node: ast.Expr) -> ast.AST | None:
        """Eliminate orphan eager actions from expression statements."""
        # Check direct orphan action call
        action = is_action_call(node.value)
        if action:
            self.has_modified = True
            return None  # Removes node from body list

        # Check eager action inside print(...)
        print_info = extract_action_from_print(node.value)
        if print_info:
            self.has_modified = True
            return None  # Removes print statement

        return self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> ast.AST | None:
        """Eliminate dead action assignments."""
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target_var = node.targets[0].id
            action = is_action_call(node.value)
            if action and (target_var.startswith("_") or target_var == "cnt"):
                self.has_modified = True
                return None
        return self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> ast.AST:
        """Remediate unbroadcasted joins and suboptimal partition operations."""
        # Transform unbroadcasted joins
        if isinstance(node.func, ast.Attribute) and node.func.attr == "join":
            if len(node.args) >= 1:
                right_df = node.args[0]
                if not is_already_broadcasted(right_df):
                    right_id = None
                    if isinstance(right_df, ast.Name):
                        right_id = right_df.id
                    elif isinstance(right_df, ast.Attribute):
                        right_id = right_df.attr

                    if right_id and is_dimension_identifier(right_id):
                        # Replace right_df with F.broadcast(right_df)
                        broadcast_call = ast.Call(
                            func=ast.Attribute(
                                value=ast.Name(id="F", ctx=ast.Load()),
                                attr="broadcast",
                                ctx=ast.Load(),
                            ),
                            args=[right_df],
                            keywords=[],
                        )
                        node.args[0] = broadcast_call
                        self.has_modified = True
                        self.injected_broadcast = True

        # Transform excessive repartition
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "repartition":
            if (
                len(node.args) == 1
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, int)
                and node.args[0].value > 200
            ):
                # Replace repartition(N) with coalesce(64)
                node.func.attr = "coalesce"
                node.args[0] = ast.Constant(value=64)
                self.has_modified = True

        # Transform dangerous coalesce(1)
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "coalesce":
            if len(node.args) == 1 and isinstance(node.args[0], ast.Constant) and node.args[0].value == 1:
                # Replace coalesce(1) with coalesce(16)
                node.args[0] = ast.Constant(value=16)
                self.has_modified = True

        # Transform missing partitionBy on write chain
        elif isinstance(node.func, ast.Attribute) and node.func.attr in TERMINAL_WRITE_ACTIONS:
            chain = get_call_chain_methods(node)
            if "write" in chain and "partitionBy" not in chain:
                # node is: <chain_before_write_terminal>.<terminal_action>(*args)
                # We want to inject .partitionBy(*keys) before the terminal call
                keys_to_use = self.inferred_partition_keys or ["order_year", "order_month"]
                partition_args = [ast.Constant(value=k) for k in keys_to_use]
                old_value = node.func.value
                partition_call = ast.Call(
                    func=ast.Attribute(
                        value=old_value,
                        attr="partitionBy",
                        ctx=ast.Load(),
                    ),
                    args=partition_args,
                    keywords=[],
                )
                node.func.value = partition_call
                self.has_modified = True

        return self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        """Convert legacy row-by-row @udf to @pandas_udf."""
        new_decorators = []
        for dec in node.decorator_list:
            if is_udf_decorator(dec):
                # Replace @udf with @pandas_udf
                if isinstance(dec, ast.Name):
                    new_dec = ast.Name(id="pandas_udf", ctx=ast.Load())
                elif isinstance(dec, ast.Attribute):
                    new_dec = ast.Attribute(value=ast.Name(id="F", ctx=ast.Load()), attr="pandas_udf", ctx=ast.Load())
                elif isinstance(dec, ast.Call):
                    # Preserves returnType argument
                    if isinstance(dec.func, ast.Attribute):
                        dec.func.attr = "pandas_udf"
                    else:
                        dec.func = ast.Name(id="pandas_udf", ctx=ast.Load())
                    new_dec = dec
                else:
                    new_dec = ast.Name(id="pandas_udf", ctx=ast.Load())
                new_decorators.append(new_dec)
                self.has_modified = True
            else:
                new_decorators.append(dec)
        node.decorator_list = new_decorators
        return self.generic_visit(node)


class AstPatcher:
    """Applies verified deterministic transformations to PySpark code."""

    def __init__(self) -> None:
        pass

    def patch(
        self,
        source_code: str,
        file_path: str = "script.py",
        tree: ast.AST | None = None,
    ) -> tuple[str, str]:
        """
        Generate patched source code and a unified diff.

        Returns:
            tuple[patched_source, unified_diff]
        """
        parsed_tree = ast.parse(source_code) if tree is None else tree

        transformer = AstTransformer(raw_source=source_code)
        transformed_tree = transformer.visit(parsed_tree)
        ast.fix_missing_locations(transformed_tree)

        # Inject import pyspark.sql.functions as F if needed and not present
        if transformer.injected_broadcast and not has_pyspark_functions_import(transformed_tree):
            import_node = create_f_import_node()
            if isinstance(transformed_tree, ast.Module):
                # Insert at top of module, after docstrings if any
                insert_idx = 0
                if (
                    transformed_tree.body
                    and isinstance(transformed_tree.body[0], ast.Expr)
                    and isinstance(transformed_tree.body[0].value, ast.Constant)
                    and isinstance(transformed_tree.body[0].value.value, str)
                ):
                    insert_idx = 1
                transformed_tree.body.insert(insert_idx, import_node)
                ast.fix_missing_locations(transformed_tree)

        # If no modifications were made, return original source and empty diff
        if not transformer.has_modified:
            return source_code, ""

        # Ensure no required body blocks are empty
        for n in ast.walk(transformed_tree):
            if hasattr(n, "body") and isinstance(n.body, list) and len(n.body) == 0 and not isinstance(n, ast.Module):
                n.body.append(ast.Pass())

        patched_source = ast.unparse(transformed_tree)
        # Ensure trailing newline
        if not patched_source.endswith("\n"):
            patched_source += "\n"

        diff = self.generate_diff(source_code, patched_source, file_path)
        return patched_source, diff

    @staticmethod
    def generate_diff(original: str, patched: str, file_path: str = "workload.py") -> str:
        """Produce standard unified diff output."""
        orig_lines = original.splitlines(keepends=True)
        patched_lines = patched.splitlines(keepends=True)
        diff_lines = list(
            difflib.unified_diff(
                orig_lines,
                patched_lines,
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path}",
            )
        )
        return "".join(diff_lines)
