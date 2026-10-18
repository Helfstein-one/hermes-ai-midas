"""Unified SQL Analyzer combining visitor inspection and patch generation."""

from __future__ import annotations

import sqlglot

from hermes_midas.sql_analyzer.models import SQLInspectionResult
from hermes_midas.sql_analyzer.patcher import SQLPatcher
from hermes_midas.sql_analyzer.visitor import SQLASTVisitor


class SQLAnalyzer:
    """Static SQL AST Inspector and FinOps optimizer."""

    def __init__(self, default_dialect: str = "snowflake") -> None:
        self.default_dialect = default_dialect

    def inspect(
        self,
        sql_content: str,
        file_path: str = "query.sql",
        dialect: str | None = None,
    ) -> SQLInspectionResult:
        active_dialect = dialect or self._detect_dialect(sql_content, file_path)
        visitor = SQLASTVisitor(dialect=active_dialect)
        anti_patterns = visitor.analyze(sql_content)

        if any(ap.pattern_id == "SQL_SYNTAX_ERROR" for ap in anti_patterns):
            syntax_err = next(ap for ap in anti_patterns if ap.pattern_id == "SQL_SYNTAX_ERROR")
            return SQLInspectionResult(
                is_valid=False,
                dialect=active_dialect,
                original_sql=sql_content,
                patched_sql=sql_content,
                diff="",
                anti_patterns=anti_patterns,
                anti_patterns_count=len(anti_patterns),
                error=syntax_err.description,
            )

        patcher = SQLPatcher(dialect=active_dialect)
        patched_sql, diff = patcher.patch(sql_content, anti_patterns)

        # Validate that patched SQL compiles cleanly in sqlglot
        try:
            sqlglot.parse(patched_sql, read=active_dialect)
            is_valid = True
            err = None
        except Exception as e:
            is_valid = False
            err = f"Patched SQL failed syntax validation: {e}"

        return SQLInspectionResult(
            is_valid=is_valid,
            dialect=active_dialect,
            original_sql=sql_content,
            patched_sql=patched_sql,
            diff=diff,
            anti_patterns=anti_patterns,
            anti_patterns_count=len(anti_patterns),
            error=err,
        )

    def _detect_dialect(self, sql_content: str, file_path: str) -> str:
        lower_path = file_path.lower()
        lower_sql = sql_content.lower()

        if "bigquery" in lower_path or "`" in sql_content or "_partitiondate" in lower_sql:
            return "bigquery"
        if "duckdb" in lower_path:
            return "duckdb"
        if "snowflake" in lower_path or "dateadd" in lower_sql or "current_date()" in lower_sql:
            return "snowflake"
        return self.default_dialect
