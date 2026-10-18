"""Unit and boundary tests for PySpark static AST analyzer and patch generator.

Tiers Covered:
- Tier 1: Feature Coverage (Orphan Actions, Unbroadcasted Joins, Partitions, Legacy UDFs, Validator)
- Tier 2: Boundary & Corner Cases (Asserts, Returns, Reads, Already Broadcasted, Syntax/Compile Errors)
"""

from __future__ import annotations

import ast

import pytest

from hermes_midas.ast_analyzer import (
    AntiPatternType,
    ASTAnalyzer,
    AstPatcher,
    AstValidator,
    LegacyUdfDetector,
    OrphanActionDetector,
    SuboptimalPartitionDetector,
    UnbroadcastedJoinDetector,
)

# ============================================================================
# Tier 1: Feature Unit Tests
# ============================================================================

@pytest.mark.tier1
def test_orphan_action_detector_identifies_bare_actions(orphan_actions_code: str):
    """Tier 1: Detect bare DataFrame action expressions (.count, .collect, .show)."""
    source_lines = orphan_actions_code.splitlines()
    tree = ast.parse(orphan_actions_code)
    detector = OrphanActionDetector(source_lines)
    matches = detector.run(tree)

    # Must detect df.count(), df.collect(), df.show(20), and dead_val = df.count()
    detected_actions = [m.action_name for m in matches if m.action_name]
    assert "count" in detected_actions
    assert "collect" in detected_actions
    assert "show" in detected_actions

    for match in matches:
        assert match.pattern_id == AntiPatternType.ORPHAN_ACTION.value
        assert match.line_start > 0
        assert match.severity in {"CRITICAL", "HIGH"}


@pytest.mark.tier1
def test_unbroadcasted_join_detector_identifies_dimension_joins(unbroadcasted_join_code: str):
    """Tier 1: Detect dimension table joins lacking broadcast hints."""
    source_lines = unbroadcasted_join_code.splitlines()
    tree = ast.parse(unbroadcasted_join_code)
    detector = UnbroadcastedJoinDetector(source_lines)
    matches = detector.run(tree)

    assert len(matches) >= 2
    target_tables = [m.target_variable or m.details.get("right_df") for m in matches]
    assert "dim_campaigns" in target_tables
    assert "lookup_status" in target_tables


@pytest.mark.tier1
def test_suboptimal_partition_detector_identifies_repartition_and_missing_partitionby(
    suboptimal_partition_code: str,
):
    """Tier 1: Detect excessive repartition(1000), coalesce(1), and missing partitionBy."""
    source_lines = suboptimal_partition_code.splitlines()
    tree = ast.parse(suboptimal_partition_code)
    detector = SuboptimalPartitionDetector(source_lines, suboptimal_partition_code)
    matches = detector.run(tree)

    descriptions = " ".join([m.description for m in matches])
    assert "repartition" in descriptions or "partition" in descriptions.lower()
    assert any(m.details.get("type") == "excessive_repartition" for m in matches)
    assert any(m.details.get("type") == "coalesce_one" for m in matches)
    assert any(m.details.get("type") == "missing_partition_by" for m in matches)


@pytest.mark.tier1
def test_legacy_udf_detector_identifies_standard_udf(legacy_udf_code: str):
    """Tier 1: Detect Python @udf decorators that introduce serialization bottlenecks."""
    source_lines = legacy_udf_code.splitlines()
    tree = ast.parse(legacy_udf_code)
    detector = LegacyUdfDetector(source_lines)
    matches = detector.run(tree)

    assert len(matches) >= 1
    assert matches[0].pattern_id == AntiPatternType.LEGACY_UDF.value
    assert matches[0].details.get("function_name") == "format_customer_tier"


@pytest.mark.tier1
def test_ast_patcher_generates_valid_transformed_code(unbroadcasted_join_code: str):
    """Tier 1: AST patcher rewrites unbroadcasted joins and injects broadcast calls."""
    patcher = AstPatcher()
    tree = ast.parse(unbroadcasted_join_code)
    detector = UnbroadcastedJoinDetector(unbroadcasted_join_code.splitlines())
    findings = detector.run(tree)

    patched_code, diff = patcher.patch(unbroadcasted_join_code, findings)
    assert "F.broadcast" in patched_code
    assert diff != ""

    # Must parse cleanly without syntax errors
    ast.parse(patched_code)


@pytest.mark.tier1
def test_ast_validator_passes_valid_code(clean_pyspark_code: str):
    """Tier 1: AstValidator passes clean valid PySpark code across all 4 gates."""
    validator = AstValidator()
    result = validator.validate(
        original_code=clean_pyspark_code,
        patched_code=clean_pyspark_code,
        diff="",
        file_path="clean.py",
    )
    assert result.is_valid is True
    assert result.gate_results.get("Gate 1: ast.parse") is True
    assert result.gate_results.get("Gate 2: compile") is True


# ============================================================================
# Tier 2: Boundary & Corner Cases
# ============================================================================

@pytest.mark.tier2
def test_orphan_action_inside_assert_not_flagged():
    """Tier 2: Action calls inside assert statements must NOT be flagged as orphan."""
    code = 'assert df.count() > 0\nassert df.first() is not None\n'
    detector = OrphanActionDetector(code.splitlines())
    matches = detector.run(ast.parse(code))
    assert len(matches) == 0


@pytest.mark.tier2
def test_orphan_action_inside_return_not_flagged():
    """Tier 2: Action calls returned from functions must NOT be flagged as orphan."""
    code = 'def get_size(df):\n    return df.count()\n'
    detector = OrphanActionDetector(code.splitlines())
    matches = detector.run(ast.parse(code))
    assert len(matches) == 0


@pytest.mark.tier2
def test_orphan_action_active_assignment_not_flagged():
    """Tier 2: Assigned actions that are subsequently read/printed must NOT be flagged as dead."""
    code = 'cnt = df.count()\nprint(f"Count is: {cnt}")\n'
    detector = OrphanActionDetector(code.splitlines())
    matches = detector.run(ast.parse(code))
    assert len(matches) == 0


@pytest.mark.tier2
def test_already_broadcasted_join_not_flagged():
    """Tier 2: Joins already wrapped in F.broadcast or broadcast must NOT be flagged."""
    code = '''from pyspark.sql import functions as F
df_fact.join(F.broadcast(dim_users), on="id")
df_fact.join(broadcast(dim_status), on="id")
'''
    detector = UnbroadcastedJoinDetector(code.splitlines())
    matches = detector.run(ast.parse(code))
    assert len(matches) == 0


@pytest.mark.tier2
def test_non_dimension_join_not_flagged():
    """Tier 2: Joins between regular fact tables (no dim_/lookup_ prefix) must NOT be flagged."""
    code = 'df_orders.join(df_transactions, on="order_id")\n'
    detector = UnbroadcastedJoinDetector(code.splitlines())
    matches = detector.run(ast.parse(code))
    assert len(matches) == 0


@pytest.mark.tier2
def test_repartition_with_column_expression_not_flagged():
    """Tier 2: repartition(10, "region") with columns is purposeful and must NOT be flagged."""
    code = 'df.repartition(10, "region")\n'
    detector = SuboptimalPartitionDetector(code.splitlines(), code)
    matches = detector.run(ast.parse(code))
    repartition_matches = [m for m in matches if "repartition" in m.description.lower()]
    assert len(repartition_matches) == 0


@pytest.mark.tier2
def test_ast_validator_catches_syntax_error(syntax_error_code: str):
    """Tier 2: AstValidator detects syntax errors and fails at Gate 1."""
    validator = AstValidator()
    result = validator.validate(
        original_code="x = 1",
        patched_code=syntax_error_code,
        diff="dummy diff",
        file_path="broken.py",
    )
    assert result.is_valid is False
    assert result.gate == "Gate 1: ast.parse"
    assert "SyntaxError" in (result.error_message or "")


@pytest.mark.tier2
def test_ast_validator_catches_compile_error():
    """Tier 2: Code with return statement outside function fails at Gate 2 (compile)."""
    code_return_outside = 'df = spark.read.parquet("s3://bucket")\nreturn df\n'
    validator = AstValidator()
    result = validator.validate(
        original_code="df = spark.read.parquet('s3://bucket')",
        patched_code=code_return_outside,
        diff="dummy diff",
        file_path="return_outside.py",
    )
    assert result.is_valid is False
    assert result.gate == "Gate 2: compile"
    assert "compilation" in (result.error_message or "").lower()


@pytest.mark.tier2
def test_ast_analyzer_empty_code():
    """Tier 2: Empty code string returns zero anti-patterns without crashing."""
    analyzer = ASTAnalyzer()
    matches = analyzer.analyze("")
    assert len(matches) == 0


@pytest.mark.tier2
def test_ast_patcher_match_case_support():
    """Verify AST patcher cleanly handles Python match-case statements when removing statements."""
    code = (
        "def process(df, status):\n"
        "    match status:\n"
        "        case 1:\n"
        "            df.count()\n"
        "        case 2:\n"
        "            df.show()\n"
    )
    analyzer = ASTAnalyzer()
    res = analyzer.inspect(code, "match_case.py")
    assert res.is_valid is True
    ast.parse(res.patched_code)
    compile(res.patched_code, "test_match.py", "exec")


@pytest.mark.tier2
def test_ast_patcher_clean_conditionals_no_spurious_else_pass():
    """Verify AST patcher does not inject spurious 'else: pass' or 'finally: pass' on clean conditionals."""
    code = (
        "def process(df, condition):\n"
        "    if condition:\n"
        "        df.count()\n"
    )
    analyzer = ASTAnalyzer()
    res = analyzer.inspect(code, "conditional.py")
    assert res.is_valid is True
    assert "else:" not in res.patched_code
    assert "finally:" not in res.patched_code
