"""Unit tests for SQL AST analysis and anti-pattern detection using sqlglot."""

from __future__ import annotations

from hermes_midas.sql_analyzer import (
    SQLAnalyzer,
    SQLASTVisitor,
    SQLPatcher,
)


def test_sql_visitor_detects_select_star() -> None:
    sql = "SELECT * FROM raw_vault.orders"
    visitor = SQLASTVisitor(dialect="snowflake")
    patterns = visitor.analyze(sql)

    pattern_ids = [p.pattern_id for p in patterns]
    assert "SELECT_STAR" in pattern_ids
    assert any("raw_vault" in (p.table_name or "") or "orders" in (p.table_name or "") for p in patterns)


def test_sql_visitor_detects_cartesian_join() -> None:
    sql = "SELECT a.id, b.name FROM raw_orders a, raw_customers b"
    visitor = SQLASTVisitor(dialect="snowflake")
    patterns = visitor.analyze(sql)

    pattern_ids = [p.pattern_id for p in patterns]
    assert "CARTESIAN_PRODUCT" in pattern_ids


def test_sql_visitor_detects_unfiltered_partition_scan() -> None:
    sql = "SELECT order_id, total_amount FROM analytics.fact_orders"
    visitor = SQLASTVisitor(dialect="snowflake")
    patterns = visitor.analyze(sql)

    pattern_ids = [p.pattern_id for p in patterns]
    assert "UNFILTERED_PARTITION_SCAN" in pattern_ids


def test_sql_visitor_clean_query_no_anti_patterns() -> None:
    sql = """
    SELECT
        orders.order_id,
        customers.customer_name,
        orders.total_amount
    FROM analytics.orders AS orders
    INNER JOIN analytics.customers AS customers
        ON orders.customer_id = customers.customer_id
    WHERE orders.order_date >= '2026-01-01'
    """
    visitor = SQLASTVisitor(dialect="snowflake")
    patterns = visitor.analyze(sql)
    assert len(patterns) == 0


def test_sql_patcher_rewrites_select_star() -> None:
    sql = "SELECT * FROM raw_vault.orders WHERE order_date >= CURRENT_DATE - 7"
    patcher = SQLPatcher(dialect="snowflake")
    patched, _diff = patcher.patch(sql)

    assert "*" not in patched
    assert "order_id" in patched
    assert "total_amount" in patched


def test_sql_patcher_replaces_cartesian_join() -> None:
    sql = "SELECT o.id, c.name FROM raw_orders o, raw_customers c WHERE o.order_date >= CURRENT_DATE"
    patcher = SQLPatcher(dialect="snowflake")
    patched, _diff = patcher.patch(sql)

    assert "INNER JOIN" in patched
    assert "ON" in patched


def test_sql_patcher_adds_partition_filter() -> None:
    sql = "SELECT id, amount FROM analytics.fact_orders"
    patcher = SQLPatcher(dialect="snowflake")
    patched, _diff = patcher.patch(sql)

    assert "WHERE" in patched
    assert "CURRENT_DATE" in patched


def test_sql_analyzer_end_to_end() -> None:
    sql = """
    WITH raw_orders AS (
        SELECT *
        FROM raw_vault.orders
    ),
    raw_customers AS (
        SELECT *
        FROM raw_vault.customers
    ),
    joined AS (
        SELECT
            raw_orders.order_id,
            raw_customers.customer_id
        FROM raw_orders, raw_customers
    )
    SELECT *
    FROM joined
    """
    analyzer = SQLAnalyzer()
    res = analyzer.inspect(sql, "models/marts/fct_customer_orders.sql", dialect="snowflake")

    assert res.is_valid is True
    assert res.anti_patterns_count > 0
    assert "SELECT_STAR" in [p.pattern_id for p in res.anti_patterns]
    assert "CARTESIAN_PRODUCT" in [p.pattern_id for p in res.anti_patterns]
    assert len(res.diff) > 0
    assert res.optimized_code != sql
    assert res.patched_code == res.optimized_code

    dict_repr = res.to_dict()
    assert dict_repr["is_valid"] is True
    assert dict_repr["anti_patterns_count"] == res.anti_patterns_count


def test_sql_analyzer_handles_syntax_errors() -> None:
    invalid_sql = "SELECT FROM WHERE GROUP BY ORDER"
    analyzer = SQLAnalyzer()
    res = analyzer.inspect(invalid_sql, "broken.sql", dialect="snowflake")

    assert res.is_valid is False
    assert res.error is not None
    assert res.anti_patterns_count > 0
    assert res.anti_patterns[0].pattern_id == "SQL_SYNTAX_ERROR"


def test_sql_analyzer_bigquery_dialect() -> None:
    bq_sql = """
    SELECT *
    FROM `gcp-project.dataset.events`
    """
    analyzer = SQLAnalyzer()
    res = analyzer.inspect(bq_sql, "queries/events.sql", dialect="bigquery")

    assert res.is_valid is True
    assert res.dialect == "bigquery"
    assert res.anti_patterns_count >= 1
    assert "SELECT_STAR" in [p.pattern_id for p in res.anti_patterns]
