"""Data models for PySpark AST analysis and patch validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AntiPatternType(StrEnum):
    """Categorization of detected PySpark anti-patterns."""
    ORPHAN_ACTION = "ORPHAN_ACTION"
    UNBROADCASTED_JOIN = "UNBROADCASTED_JOIN"
    SUBOPTIMAL_PARTITION = "SUBOPTIMAL_PARTITION"
    LEGACY_UDF = "LEGACY_UDF"


class Severity(StrEnum):
    """Severity ratings for compute waste and performance hazards."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


@dataclass
class AntiPatternMatch:
    """Represents a specific anti-pattern match identified within PySpark source code."""
    pattern_id: str
    pattern_name: str
    line_start: int
    line_end: int
    col_offset: int = 0
    end_col_offset: int = 0
    severity: str = "HIGH"
    description: str = ""
    remediation_strategy: str = ""
    code_snippet: str = ""
    target_variable: str | None = None
    action_name: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert finding into a serializable dictionary."""
        return {
            "pattern_id": self.pattern_id,
            "pattern_name": self.pattern_name,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "col_offset": self.col_offset,
            "end_col_offset": self.end_col_offset,
            "severity": self.severity,
            "description": self.description,
            "remediation_strategy": self.remediation_strategy,
            "code_snippet": self.code_snippet,
            "target_variable": self.target_variable,
            "action_name": self.action_name,
            "details": self.details,
        }

    def dict(self) -> dict[str, Any]:
        """Pydantic v1 compatibility alias."""
        return self.to_dict()

    def model_dump(self) -> dict[str, Any]:
        """Pydantic v2 compatibility alias."""
        return self.to_dict()


# Alias for compatibility with orchestrator / trigger contracts
AntiPatternDetection = AntiPatternMatch


@dataclass
class ValidationResult:
    """Result of the 4-gate AST patch validation pipeline."""
    is_valid: bool = True
    gate: str = ""
    error_message: str | None = None
    gate_results: dict[str, bool] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        """Boolean compatibility property."""
        return self.is_valid

    def to_dict(self) -> dict[str, Any]:
        """Convert validation result into dictionary."""
        return {
            "is_valid": self.is_valid,
            "valid": self.is_valid,
            "gate": self.gate,
            "error_message": self.error_message,
            "gate_results": self.gate_results,
        }

    def dict(self) -> dict[str, Any]:
        """Pydantic v1 compatibility alias."""
        return self.to_dict()

    def model_dump(self) -> dict[str, Any]:
        """Pydantic v2 compatibility alias."""
        return self.to_dict()


@dataclass
class ASTInspectionResult:
    """Aggregated output from static AST analysis and patch generation."""
    file_path: str = ""
    anti_patterns: list[AntiPatternMatch] = field(default_factory=list)
    patched_code: str = ""
    is_valid: bool = True
    diff: str = ""
    validation_result: ValidationResult | None = None
    error: str | None = None

    @property
    def valid(self) -> bool:
        """Boolean compatibility property."""
        return self.is_valid

    @property
    def anti_patterns_count(self) -> int:
        """Count of detected anti-patterns."""
        return len(self.anti_patterns)

    def to_dict(self) -> dict[str, Any]:
        """Convert inspection result into dictionary."""
        return {
            "file_path": self.file_path,
            "anti_patterns": [p.to_dict() for p in self.anti_patterns],
            "anti_patterns_count": self.anti_patterns_count,
            "patched_code": self.patched_code,
            "is_valid": self.is_valid,
            "valid": self.is_valid,
            "diff": self.diff,
            "validation_result": self.validation_result.to_dict() if self.validation_result else None,
            "error": self.error,
        }

    def dict(self) -> dict[str, Any]:
        """Pydantic v1 compatibility alias."""
        return self.to_dict()

    def model_dump(self) -> dict[str, Any]:
        """Pydantic v2 compatibility alias."""
        return self.to_dict()
