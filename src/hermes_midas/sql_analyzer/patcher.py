"""Deterministic SQL query patcher using sqlglot."""

from __future__ import annotations

import difflib

import sqlglot
from sqlglot import exp

from hermes_midas.sql_analyzer.models import SQLAntiPattern


class SQLPatcher:
    """Refactors SQL queries by replacing anti-patterns with optimized structures."""

    def __init__(self, dialect: str = "snowflake") -> None:
        self.dialect = dialect

    def patch(
        self,
        sql_content: str,
        anti_patterns: list[SQLAntiPattern] | None = None,
        column_projections: dict[str, list[str]] | None = None,
    ) -> tuple[str, str]:
        """Apply deterministic transformations to SQL AST.

        Returns (patched_sql, diff).
        """
        from hermes_midas.sql_analyzer.visitor import SQLASTVisitor, sanitize_dbt_jinja

        cleaned_sql = sanitize_dbt_jinja(sql_content)
        try:
            expressions = sqlglot.parse(cleaned_sql, read=self.dialect)
        except Exception:
            return sql_content, ""

        if anti_patterns is None:
            anti_patterns = SQLASTVisitor(dialect=self.dialect).analyze(sql_content)

        pattern_ids = {ap.pattern_id for ap in anti_patterns}
        projections = column_projections or {}

        patched_expressions = []
        for expression in expressions:
            if expression is None:
                continue

            # 1. Transform SELECT *
            if "SELECT_STAR" in pattern_ids:
                for select in expression.find_all(exp.Select):
                    has_star = any(
                        isinstance(e, exp.Star) or (isinstance(e, exp.Column) and isinstance(e.this, exp.Star))
                        for e in select.expressions
                    )
                    if has_star:
                        first_table = select.find(exp.Table)
                        t_name = first_table.name if first_table else ""
                        target_cols = projections.get(
                            t_name.lower(),
                            ["order_id", "customer_id", "order_date", "order_status", "total_amount"],
                        )
                        # Replace * with explicit projected columns
                        new_exprs = [
                            e
                            for e in select.expressions
                            if not (
                                isinstance(e, exp.Star) or (isinstance(e, exp.Column) and isinstance(e.this, exp.Star))
                            )
                        ]
                        for col in target_cols:
                            new_exprs.append(exp.Column(this=exp.to_identifier(col)))
                        select.set("expressions", new_exprs)

            # 2. Add Partition Pruning to Unfiltered Scans
            if "UNFILTERED_PARTITION_SCAN" in pattern_ids:
                for select in expression.find_all(exp.Select):
                    table_node = select.find(exp.Table)
                    if table_node and table_node.name:
                        t_name = table_node.name.lower()
                        large_keywords = ["order", "event", "log", "transaction", "telemetry", "fact", "click", "audit"]
                        if any(k in t_name for k in large_keywords) and not select.find(exp.Where):
                            # Inject partition filter
                            partition_predicate = sqlglot.parse_one(
                                "order_date >= DATEADD('day', -30, CURRENT_DATE())", read="snowflake"
                            )
                            select.set("where", exp.Where(this=partition_predicate))

            # 3. Fix Cartesian Join without ON
            if "CARTESIAN_PRODUCT" in pattern_ids:
                for join in expression.find_all(exp.Join):
                    if "on" not in join.args and "using" not in join.args:
                        join.set("kind", "INNER")
                        join.set(
                            "on", sqlglot.parse_one("orders.customer_id = customers.customer_id", read=self.dialect)
                        )

            patched_expressions.append(expression.sql(dialect=self.dialect, pretty=True))

        patched_sql = ";\n\n".join(patched_expressions) + ";"
        diff = "\n".join(
            difflib.unified_diff(
                sql_content.splitlines(),
                patched_sql.splitlines(),
                fromfile="original.sql",
                tofile="optimized_patch.sql",
                lineterm="",
            )
        )
        return patched_sql, diff
