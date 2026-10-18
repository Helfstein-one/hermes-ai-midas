"""Unified PySpark AST analyzer orchestrating pattern detection, patching, and validation."""

from __future__ import annotations

import ast
from pathlib import Path

from hermes_midas.ast_analyzer.models import (
    AntiPatternMatch,
    ASTInspectionResult,
    ValidationResult,
)
from hermes_midas.ast_analyzer.patcher import AstPatcher
from hermes_midas.ast_analyzer.patterns.legacy_udf import LegacyUdfDetector
from hermes_midas.ast_analyzer.patterns.orphan_actions import OrphanActionDetector
from hermes_midas.ast_analyzer.patterns.partitions import SuboptimalPartitionDetector
from hermes_midas.ast_analyzer.patterns.unbroadcasted_joins import (
    UnbroadcastedJoinDetector,
)
from hermes_midas.ast_analyzer.validator import AstValidator


class ASTAnalyzer:
    """Orchestrates static AST pattern matching, automated patching, and 4-gate verification."""

    def __init__(self, custom_dimensions: set[str] | None = None) -> None:
        self.custom_dimensions = custom_dimensions or set()
        self.patcher = AstPatcher()
        self.validator = AstValidator()

    def analyze(self, source_code: str, file_path: str = "workload.py") -> list[AntiPatternMatch]:
        """Detect all PySpark anti-patterns in the given source code."""
        try:
            tree = ast.parse(source_code, filename=file_path)
        except SyntaxError as e:
            # Return finding for syntax error
            return [
                AntiPatternMatch(
                    pattern_id="SYNTAX_ERROR",
                    pattern_name="Source Syntax Error",
                    line_start=e.lineno or 1,
                    line_end=e.lineno or 1,
                    col_offset=e.offset or 0,
                    severity="CRITICAL",
                    description=f"Source code cannot be parsed: {e.msg}",
                    remediation_strategy="Fix syntax error before AST analysis.",
                    code_snippet=e.text or "",
                )
            ]

        source_lines = source_code.splitlines()
        matches: list[AntiPatternMatch] = []

        # 1. Orphan actions
        orphan_detector = OrphanActionDetector(source_lines)
        matches.extend(orphan_detector.run(tree))

        # 2. Unbroadcasted joins
        unbroadcasted_detector = UnbroadcastedJoinDetector(source_lines, self.custom_dimensions)
        matches.extend(unbroadcasted_detector.run(tree))

        # 3. Suboptimal partitions
        partition_detector = SuboptimalPartitionDetector(source_lines, source_code)
        matches.extend(partition_detector.run(tree))

        # 4. Legacy UDFs
        udf_detector = LegacyUdfDetector(source_lines)
        matches.extend(udf_detector.run(tree))

        # Sort matches by line number
        matches.sort(key=lambda m: (m.line_start, m.col_offset))
        return matches

    def analyze_file(self, file_path: str | Path) -> list[AntiPatternMatch]:
        """Read a file from disk and detect all anti-patterns."""
        path_obj = Path(file_path)
        source_code = path_obj.read_text(encoding="utf-8")
        return self.analyze(source_code, file_path=str(path_obj))

    def inspect(self, source_code: str, file_path: str = "workload.py") -> ASTInspectionResult:
        """Run complete inspection: detection, patching, and 4-gate validation."""
        anti_patterns = self.analyze(source_code, file_path=file_path)

        # If syntax error in original source, return invalid result
        syntax_errors = [m for m in anti_patterns if m.pattern_id == "SYNTAX_ERROR"]
        if syntax_errors:
            err = syntax_errors[0]
            val_res = ValidationResult(
                is_valid=False,
                gate="Gate 1: ast.parse",
                error_message=err.description,
            )
            return ASTInspectionResult(
                file_path=file_path,
                anti_patterns=anti_patterns,
                patched_code=source_code,
                is_valid=False,
                diff="",
                validation_result=val_res,
                error=err.description,
            )

        # If no anti-patterns found, return valid with original source
        if not anti_patterns:
            val_res = ValidationResult(is_valid=True, gate="All gates passed")
            return ASTInspectionResult(
                file_path=file_path,
                anti_patterns=[],
                patched_code=source_code,
                is_valid=True,
                diff="",
                validation_result=val_res,
            )

        # Generate patch and unified diff
        patched_code, diff = self.patcher.patch(source_code, file_path=file_path)

        # Run 4-gate validation pipeline
        val_res = self.validator.validate(
            original_code=source_code,
            patched_code=patched_code,
            diff=diff,
            file_path=file_path,
        )

        return ASTInspectionResult(
            file_path=file_path,
            anti_patterns=anti_patterns,
            patched_code=patched_code,
            is_valid=val_res.is_valid,
            diff=diff,
            validation_result=val_res,
            error=val_res.error_message,
        )

    def inspect_file(self, file_path: str | Path) -> ASTInspectionResult:
        """Inspect a file on disk."""
        path_obj = Path(file_path)
        source_code = path_obj.read_text(encoding="utf-8")
        return self.inspect(source_code, file_path=str(path_obj))

    def patch(self, source_code: str, file_path: str = "workload.py") -> ASTInspectionResult:
        """Convenience alias for inspect."""
        return self.inspect(source_code, file_path=file_path)

    def patch_file(self, file_path: str | Path) -> ASTInspectionResult:
        """Convenience alias for inspect_file."""
        return self.inspect_file(file_path)
