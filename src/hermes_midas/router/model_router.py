"""Multi-tier model router cascading from Ollama to Cloud to Deterministic AST."""

from __future__ import annotations

import os

import httpx

from hermes_midas.ast_analyzer import ASTAnalyzer, AstPatcher, AstValidator
from hermes_midas.router.fallback_engine import DeterministicFallbackEngine
from hermes_midas.router.models import (
    ModelTier,
    RefactoringRequest,
    RefactoringResponse,
)


class DeterministicModelRouter:
    """Multi-tier router with guaranteed deterministic offline fallback.

    Cascade:
    1. Tier 1: Local Ollama (e.g. qwen2.5-coder / deepseek-coder)
    2. Tier 2: Free Cloud API (Groq / Gemini)
    3. Tier 3: Deterministic AST Offline Fallback (hermes-ast-transformer-v1)
    """

    def __init__(
        self,
        offline_mode: bool = True,
        ollama_host: str = "http://localhost:11434",
        timeout_seconds: float = 3.0,
    ) -> None:
        self.offline_mode = offline_mode
        self.ollama_host = ollama_host
        self.timeout_seconds = timeout_seconds
        self.analyzer = ASTAnalyzer()
        self.validator = AstValidator()
        self.fallback_engine = DeterministicFallbackEngine(self.analyzer, self.validator)

    async def route_and_optimize(self, request: RefactoringRequest) -> RefactoringResponse:
        """Route request through model tiers, falling back gracefully to deterministic AST."""
        fallback_chain: list[str] = []

        # If offline mode is enforced, jump straight to Tier 3
        if self.offline_mode or os.environ.get("MIDAS_OFFLINE_MODE") == "1" or request.offline_only:
            fallback_chain.append("offline_mode_enforced -> tier_3")
            return self._execute_tier_3(request, fallback_chain)

        # Attempt Tier 1 (Ollama)
        fallback_chain.append("tier_1_ollama_attempt")
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.post(
                    f"{self.ollama_host}/api/generate",
                    json={
                        "model": "qwen2.5-coder:7b",
                        "prompt": f"Refactor PySpark code to remove anti-patterns:\n{request.original_code}",
                        "stream": False,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    optimized = data.get("response", "").strip()
                    if optimized:
                        diff = AstPatcher.generate_diff(request.original_code, optimized, request.file_path)
                        val = self.validator.validate(
                            request.original_code, optimized, diff=diff, file_path=request.file_path
                        )
                        if val.is_valid:
                            return RefactoringResponse(
                                optimized_code=optimized,
                                diff=diff,
                                explanation="Refactored via local Ollama (qwen2.5-coder:7b).",
                                tier_used=ModelTier.LOCAL_OLLAMA,
                                provider_name="ollama-local",
                                fallback_chain=fallback_chain,
                                ast_valid=True,
                            )
            fallback_chain.append("tier_1_failed -> cascade_to_tier_2")
        except (httpx.HTTPError, KeyError, IndexError, AttributeError, ValueError, OSError, RuntimeError):
            fallback_chain.append("tier_1_failed -> cascade_to_tier_2")

        # Attempt Tier 2 (Free Cloud API)
        fallback_chain.append("tier_2_cloud_attempt")
        groq_key = os.environ.get("GROQ_API_KEY")
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if not groq_key and not gemini_key:
            fallback_chain.append("tier_2_failed -> cascade_to_tier_3")
        else:
            try:
                # Attempt call to Groq or Gemini OpenAI-compatible API
                endpoint = (
                    "https://api.groq.com/openai/v1/chat/completions"
                    if groq_key
                    else "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
                )
                api_key = groq_key or gemini_key
                model_name = "llama-3.3-70b-versatile" if groq_key else "gemini-2.5-flash"
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    resp = await client.post(
                        endpoint,
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={
                            "model": model_name,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": f"Refactor PySpark code removing anti-patterns:\n{request.original_code}",
                                }
                            ],
                        },
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        choices = data.get("choices", [])
                        if not choices:
                            fallback_chain.append("tier_2_empty_choices -> cascade_to_tier_3")
                            return self._execute_tier_3(request, fallback_chain)
                        optimized = choices[0].get("message", {}).get("content", "").strip()
                        diff = AstPatcher.generate_diff(request.original_code, optimized, request.file_path)
                        val = self.validator.validate(
                            request.original_code, optimized, diff=diff, file_path=request.file_path
                        )
                        if val.is_valid:
                            return RefactoringResponse(
                                optimized_code=optimized,
                                diff=diff,
                                explanation=f"Refactored via cloud provider ({model_name}).",
                                tier_used=ModelTier.FREE_TIER_CLOUD,
                                provider_name=f"cloud-{model_name}",
                                fallback_chain=fallback_chain,
                                ast_valid=True,
                            )
                fallback_chain.append("tier_2_failed -> cascade_to_tier_3")
            except (httpx.HTTPError, KeyError, IndexError, AttributeError, ValueError, OSError, RuntimeError):
                fallback_chain.append("tier_2_failed -> cascade_to_tier_3")

        # Tier 3 Deterministic Fallback
        return self._execute_tier_3(request, fallback_chain)

    def _execute_tier_3(self, request: RefactoringRequest, fallback_chain: list[str]) -> RefactoringResponse:
        """Execute deterministic AST patching with validation."""
        inspection = self.analyzer.inspect(request.original_code, request.file_path)

        return RefactoringResponse(
            optimized_code=inspection.patched_code,
            diff=inspection.diff,
            explanation=f"Remediated {len(inspection.anti_patterns)} anti-patterns via deterministic AST rules.",
            tier_used=ModelTier.DETERMINISTIC_OFFLINE,
            provider_name="hermes-ast-transformer-v1",
            fallback_chain=fallback_chain,
            ast_valid=inspection.is_valid,
        )


# Backward-compatible alias
ModelRouter = DeterministicModelRouter
