"""Domain models for SQL AST analysis and anti-pattern detection."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SQLAntiPattern(BaseModel):
    """Detected SQL query anti-pattern."""

    pattern_id: str
    description: str
    severity: str = "HIGH"
    line_number: int | None = None
    table_name: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "description": self.description,
            "severity": self.severity,
            "line_number": self.line_number,
            "table_name": self.table_name,
            "details": self.details,
        }


class SQLInspectionResult(BaseModel):
    """Result of static SQL AST inspection."""

    is_valid: bool = True
    dialect: str = "snowflake"
    original_sql: str
    patched_sql: str
    diff: str = ""
    anti_patterns: list[SQLAntiPattern] = Field(default_factory=list)
    anti_patterns_count: int = 0
    error: str | None = None

    @property
    def patched_code(self) -> str:
        return self.patched_sql

    @property
    def optimized_code(self) -> str:
        return self.patched_sql

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "dialect": self.dialect,
            "anti_patterns_count": self.anti_patterns_count,
            "anti_patterns": [p.to_dict() for p in self.anti_patterns],
            "diff": self.diff,
            "error": self.error,
        }
