"""PR Deduplication Engine and deterministic fingerprinting."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic import BaseModel, Field


class PRAction(str):
    """Possible outcomes of PR deduplication evaluation."""

    CREATED = "CREATED"
    UPDATED = "UPDATED"
    SKIPPED_DEDUPLICATED = "SKIPPED_DEDUPLICATED"
    SKIPPED_NO_ISSUES = "SKIPPED_NO_ISSUES"


class MockPR(BaseModel):
    """Representation of an open or closed Pull Request for deduplication evaluation."""

    id: int = 1
    title: str = ""
    body: str = ""
    head_branch: str = ""
    base_branch: str = "main"
    is_open: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


def compute_deterministic_fingerprint(script_path: str, engine: str, anti_pattern_ids: list[str]) -> str:
    """Compute 16-character SHA-256 deterministic fingerprint with delimiter escaping."""
    normalized_patterns = sorted(anti_pattern_ids)
    payload = json.dumps([script_path, engine, normalized_patterns], separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def generate_branch_name(script_path: str, fingerprint: str) -> str:
    """Generate standardized git branch name: midas/finops-{slug}-{fingerprint}."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", script_path).strip("-").lower()
    return f"midas/finops-{slug}-{fingerprint}"


class PRDeduplicationEngine:
    """Evaluates whether to create, update, or skip a pull request based on fingerprint."""

    def __init__(self, existing_prs: list[Any] | None = None, git_provider: Any | None = None) -> None:
        self.existing_prs: list[Any] = existing_prs if existing_prs is not None else []
        self.git_provider = git_provider

    def evaluate(
        self, script_path: str, engine: str, anti_pattern_ids: list[str], repo: str | None = None
    ) -> tuple[str, Any | None, str]:
        """Evaluate deduplication status for a workload candidate.

        Returns:
            Tuple of (action, matched_pr, fingerprint)
        """
        if not anti_pattern_ids:
            return PRAction.SKIPPED_NO_ISSUES, None, ""

        fp = compute_deterministic_fingerprint(script_path, engine, anti_pattern_ids)

        prs = list(self.existing_prs)
        if not prs and self.git_provider and repo:
            # Query provider for open PRs
            raw_prs = self.git_provider.list_open_prs(repo)
            for rp in raw_prs:
                # Try to extract metadata if present
                meta = rp.get("metadata", {})
                prs.append(
                    MockPR(
                        id=rp.get("pr_number") or rp.get("number") or rp.get("id", 1),
                        title=rp.get("title", ""),
                        body=rp.get("body", ""),
                        head_branch=rp.get("branch") or rp.get("head", {}).get("ref", ""),
                        is_open=rp.get("status") in ("OPEN", "CREATED", "UPDATED", None),
                        metadata=meta,
                    )
                )

        for pr in prs:
            is_open = pr.get("is_open", True) if isinstance(pr, dict) else getattr(pr, "is_open", True)
            if not is_open:
                continue

            metadata = pr.get("metadata", {}) if isinstance(pr, dict) else getattr(pr, "metadata", {})
            pr_fp = metadata.get("fingerprint")
            pr_script = metadata.get("script_path")

            # If metadata didn't have script_path, check branch or title/body
            if not pr_script:
                branch = pr.get("head_branch") if isinstance(pr, dict) else getattr(pr, "head_branch", "")
                if fp in branch:
                    pr_script = script_path
                    pr_fp = fp

            if pr_script == script_path:
                if pr_fp == fp:
                    return PRAction.SKIPPED_DEDUPLICATED, pr, fp
                else:
                    return PRAction.UPDATED, pr, fp

        return PRAction.CREATED, None, fp
