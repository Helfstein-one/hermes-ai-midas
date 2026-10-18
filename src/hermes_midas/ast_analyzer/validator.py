"""Harness for 4-gate AST patch validation."""

from __future__ import annotations

import ast

from hermes_midas.ast_analyzer.models import ValidationResult
from hermes_midas.ast_analyzer.patterns.legacy_udf import LegacyUdfDetector
from hermes_midas.ast_analyzer.patterns.orphan_actions import OrphanActionDetector
from hermes_midas.ast_analyzer.patterns.partitions import SuboptimalPartitionDetector
from hermes_midas.ast_analyzer.patterns.unbroadcasted_joins import (
    UnbroadcastedJoinDetector,
)


class AstValidator:
    """Enforces the 4-gate validation pipeline on refactored PySpark code."""

    def __init__(self) -> None:
        pass

    def validate(
        self,
        original_code: str,
        patched_code: str,
        diff: str = "",
        file_path: str = "workload.py",
    ) -> ValidationResult:
        """
        Execute the 4 validation gates sequentially.

        Returns:
            ValidationResult indicating pass/fail status, failing gate, and error description.
        """
        gate_results: dict[str, bool] = {
            "Gate 1: ast.parse": False,
            "Gate 2: compile": False,
            "Gate 3: semantic": False,
            "Gate 4: diff": False,
        }

        # Gate 1: ast.parse
        try:
            patched_tree = ast.parse(patched_code, filename=file_path)
            gate_results["Gate 1: ast.parse"] = True
        except SyntaxError as e:
            return ValidationResult(
                is_valid=False,
                gate="Gate 1: ast.parse",
                error_message=f"SyntaxError in generated AST patch: {e.msg} at line {e.lineno}",
                gate_results=gate_results,
            )
        except Exception as e:  # noqa: BLE001
            return ValidationResult(
                is_valid=False,
                gate="Gate 1: ast.parse",
                error_message=f"AST parsing failed: {e}",
                gate_results=gate_results,
            )

        # Gate 2: compile(..., mode="exec")
        try:
            compile(patched_code, filename=f"<ast_patch:{file_path}>", mode="exec")
            gate_results["Gate 2: compile"] = True
        except (SyntaxError, ValueError, TypeError) as e:
            return ValidationResult(
                is_valid=False,
                gate="Gate 2: compile",
                error_message=f"Bytecode compilation error: {e}",
                gate_results=gate_results,
            )
        except Exception as e:  # noqa: BLE001
            return ValidationResult(
                is_valid=False,
                gate="Gate 2: compile",
                error_message=f"Compilation failed unexpectedly: {e}",
                gate_results=gate_results,
            )

        # Gate 3: Semantic Verification (re-run pattern detectors)
        try:
            source_lines = patched_code.splitlines()
            orphan_matches = OrphanActionDetector(source_lines).run(patched_tree)
            unbroadcasted_matches = UnbroadcastedJoinDetector(source_lines).run(patched_tree)
            _partition_matches = SuboptimalPartitionDetector(source_lines, patched_code).run(patched_tree)
            _udf_matches = LegacyUdfDetector(source_lines).run(patched_tree)

            remaining_critical_issues = len(orphan_matches) + len(unbroadcasted_matches)
            # If critical issues remain unaddressed after patching, fail semantic gate
            if remaining_critical_issues > 0 and original_code != patched_code:
                return ValidationResult(
                    is_valid=False,
                    gate="Gate 3: semantic",
                    error_message=(
                        f"Semantic verification failed: {len(orphan_matches)} orphan actions and "
                        f"{len(unbroadcasted_matches)} unbroadcasted joins persist in patched code."
                    ),
                    gate_results=gate_results,
                )
            gate_results["Gate 3: semantic"] = True
        except Exception as e:  # noqa: BLE001
            return ValidationResult(
                is_valid=False,
                gate="Gate 3: semantic",
                error_message=f"Semantic verification error: {e}",
                gate_results=gate_results,
            )

        # Gate 4: Unified Diff Validation
        if original_code != patched_code and not diff.strip():
            return ValidationResult(
                is_valid=False,
                gate="Gate 4: diff",
                error_message="Unified diff is empty despite source code transformation.",
                gate_results=gate_results,
            )
        gate_results["Gate 4: diff"] = True

        return ValidationResult(
            is_valid=True,
            gate="All gates passed",
            error_message=None,
            gate_results=gate_results,
        )
