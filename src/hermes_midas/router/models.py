"""Data models for Multi-Tier Model Router."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ModelTier(StrEnum):
    """Execution tiers for the optimization model router."""
    LOCAL_OLLAMA = "local_ollama"
    FREE_TIER_CLOUD = "free_tier_cloud"
    DETERMINISTIC_OFFLINE = "deterministic_offline"


class RefactoringRequest(BaseModel):
    """Input request for code optimization."""
    file_path: str
    original_code: str
    anti_patterns: list[dict[str, Any]] = Field(default_factory=list)
    engine: str = "glue"
    offline_only: bool = True
    roi_summary: dict[str, Any] | None = None


class RefactoringResponse(BaseModel):
    """Output response from code optimization router."""
    optimized_code: str
    diff: str
    explanation: str
    tier_used: ModelTier
    provider_name: str
    fallback_chain: list[str] = Field(default_factory=list)
    ast_valid: bool
