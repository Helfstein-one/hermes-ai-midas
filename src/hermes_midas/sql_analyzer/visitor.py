"""SQL AST Visitor using sqlglot to detect FinOps anti-patterns."""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

from hermes_midas.sql_analyzer.models import SQLAntiPattern


def sanitize_dbt_jinja(sql_content: str) -> str:
    """Strip or normalize dbt Jinja expressions ({{ ... }} and {% ... %}) for SQL AST parsing."""
    cleaned = re.sub(r"\{\{\s*(?:ref|source)\s*\([^)]*['\"]([^'\"]+)['\"]\s*\)\s*\}\}", r"\1", sql_content)
    cleaned = re.sub(r"\{\{.*?\}\}", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"\{%.*?%\}", "", cleaned, flags=re.DOTALL)
    return cleaned


class SQLASTVisitor:
    """Visits SQL AST nodes and flags compute and storage waste patterns."""

    def __init__(self, dialect: str = "snowflake") -> None:
        self.dialect = dialect

    def analyze(self, sql_content: str) -> list[SQLAntiPattern]:
        anti_patterns: list[SQLAntiPattern] = []
        cleaned_sql = sanitize_dbt_jinja(sql_content)
        try:
            parsed = sqlglot.parse(cleaned_sql, read=self.dialect)
        except Exception as e:
            return [
                SQLAntiPattern(
                    pattern_id="SQL_SYNTAX_ERROR",
                    description=f"SQL syntax error in dialect {self.dialect}: {e}",
                    severity="BLOCKER",
                    details={"error": str(e)},
                )
            ]

        for expression in parsed:
            if expression is None:
                continue

            # 1. Detect SELECT *
            for select in expression.find_all(exp.Select):
                has_star = False
                for expr in select.expressions:
                    if isinstance(expr, exp.Star) or (isinstance(expr, exp.Column) and isinstance(expr.this, exp.Star)):
                        has_star = True
                        break

                if has_star:
                    first_table = select.find(exp.Table)
                    from_table = first_table.name if first_table else ""

                    anti_patterns.append(
                        SQLAntiPattern(
                            pattern_id="SELECT_STAR",
                            description="Full column scan via SELECT * on columnar Data Warehouse table causes excessive I/O and byte scanning costs.",
                            severity="HIGH",
                            table_name=from_table or None,
                            details={"recommendation": "Explicitly project only required schema columns"},
                        )
                    )

            # 2. Detect Cartesian Products / Joins without ON
            for join in expression.find_all(exp.Join):
                is_cross = join.kind == "CROSS" or ("on" not in join.args and "using" not in join.args)
                if is_cross:
                    join_table = ""
                    if isinstance(join.this, exp.Table):
                        join_table = join.this.name
                    anti_patterns.append(
                        SQLAntiPattern(
                            pattern_id="CARTESIAN_PRODUCT",
                            description=f"Cartesian join or unconstrained join on '{join_table or 'table'}' without ON/USING predicates produces quadratic row explosion.",
                            severity="CRITICAL",
                            table_name=join_table or None,
                            details={
                                "recommendation": "Add strict equality ON predicates or replace with bounded window filter"
                            },
                        )
                    )

            # 3. Detect Unfiltered Scans on Large / Partitioned Tables
            for select in expression.find_all(exp.Select):
                table_node = select.find(exp.Table)
                if table_node and table_node.name:
                    t_name = table_node.name.lower()
                    large_keywords = ["order", "event", "log", "transaction", "telemetry", "fact", "click", "audit"]
                    if any(k in t_name for k in large_keywords):
                        where_node = select.find(exp.Where)
                        if not where_node:
                            anti_patterns.append(
                                SQLAntiPattern(
                                    pattern_id="UNFILTERED_PARTITION_SCAN",
                                    description=f"Full table scan on large transactional table '{table_node.name}' without date/time partition filtering.",
                                    severity="HIGH",
                                    table_name=table_node.name,
                                    details={
                                        "recommendation": "Add partition date filter (e.g. WHERE event_date >= CURRENT_DATE - 30)"
                                    },
                                )
                            )

        return anti_patterns
