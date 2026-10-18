"""Deterministic AST offline fallback engine for PySpark refactoring."""

from __future__ import annotations

from hermes_midas.ast_analyzer import ASTAnalyzer, ASTInspectionResult, AstValidator


class DeterministicFallbackEngine:
    """Offline deterministic code refactoring using PySpark static AST rewriter."""

    def __init__(self, analyzer: ASTAnalyzer | None = None, validator: AstValidator | None = None) -> None:
        self.analyzer = analyzer or ASTAnalyzer()
        self.validator = validator or AstValidator()

    def refactor(self, code: str, file_path: str = "") -> ASTInspectionResult:
        """Analyze and patch code using deterministic AST transformation rules."""
        return self.analyzer.inspect(code, file_path)
