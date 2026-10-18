"""Adversarial stress tests for Multi-Tier Model Router & Deterministic Offline Fallback.

Focus areas:
- Offline mode direct routing and deterministic AST transformation execution
- External endpoint failures, timeouts, and connection errors (Ollama & Cloud API)
- Bytecode compilation and AST syntax validation of router-generated code
- Edge-case bugs in model router:
  * Calling non-existent method validate_patch on AstValidator
  * IndexError on empty choices list from cloud provider
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from hermes_midas.router.model_router import DeterministicModelRouter
from hermes_midas.router.models import ModelTier, RefactoringRequest


@pytest.fixture
def orphan_actions_pyspark_code() -> str:
    return """from pyspark.sql import SparkSession
spark = SparkSession.builder.appName("Test").getOrCreate()
df = spark.read.parquet("s3://bucket/data/")
df.count()
df.collect()
df.write.parquet("s3://bucket/out/")
"""


@pytest.fixture
def unbroadcasted_join_pyspark_code() -> str:
    return """from pyspark.sql import SparkSession
spark = SparkSession.builder.appName("Test").getOrCreate()
df_fact = spark.read.parquet("s3://bucket/fact/")
dim_cust = spark.read.parquet("s3://bucket/dim_cust/")
df_joined = df_fact.join(dim_cust, on="cust_id")
df_joined.write.parquet("s3://bucket/out/")
"""


# ============================================================================
# 1. Deterministic AST Fallback Clean Execution Verification
# ============================================================================


@pytest.mark.tier1
@pytest.mark.asyncio
async def test_deterministic_fallback_executes_cleanly_on_orphan_actions(orphan_actions_pyspark_code):
    """Tier 3 deterministic fallback removes orphan actions and compiles cleanly."""
    router = DeterministicModelRouter(offline_mode=True)
    req = RefactoringRequest(
        file_path="jobs/orphan_job.py",
        original_code=orphan_actions_pyspark_code,
        engine="glue",
        offline_only=True,
    )
    res = await router.route_and_optimize(req)

    assert res.tier_used == ModelTier.DETERMINISTIC_OFFLINE
    assert res.provider_name == "hermes-ast-transformer-v1"
    assert res.ast_valid is True
    assert "df.count()" not in res.optimized_code
    assert "df.collect()" not in res.optimized_code
    assert res.diff != ""

    # Verify bytecode compilation
    compiled = compile(res.optimized_code, "<test_patch>", "exec")
    assert compiled is not None


@pytest.mark.tier1
@pytest.mark.asyncio
async def test_deterministic_fallback_executes_cleanly_on_unbroadcasted_join(unbroadcasted_join_pyspark_code):
    """Tier 3 deterministic fallback adds broadcast hint and compiles cleanly."""
    router = DeterministicModelRouter(offline_mode=True)
    req = RefactoringRequest(
        file_path="jobs/join_job.py",
        original_code=unbroadcasted_join_pyspark_code,
        engine="emr_serverless",
        offline_only=True,
    )
    res = await router.route_and_optimize(req)

    assert res.tier_used == ModelTier.DETERMINISTIC_OFFLINE
    assert res.ast_valid is True
    assert "broadcast" in res.optimized_code

    compiled = compile(res.optimized_code, "<test_patch>", "exec")
    assert compiled is not None


# ============================================================================
# 2. External Endpoint Failures and Timeout Cascades
# ============================================================================


@pytest.mark.tier2
@pytest.mark.asyncio
async def test_router_cascades_to_tier3_on_endpoint_timeouts(monkeypatch, orphan_actions_pyspark_code):
    """When both Ollama and Cloud endpoints timeout, router cascades gracefully to Tier 3."""
    monkeypatch.setenv("MIDAS_OFFLINE_MODE", "0")
    monkeypatch.setenv("GROQ_API_KEY", "mock-groq-key")
    router = DeterministicModelRouter(offline_mode=False, timeout_seconds=0.1)

    req = RefactoringRequest(
        file_path="jobs/timeout_test.py",
        original_code=orphan_actions_pyspark_code,
        engine="glue",
        offline_only=False,
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        # Simulate ReadTimeout on both tier 1 and tier 2
        mock_post.side_effect = [
            httpx.ReadTimeout("Ollama timed out"),
            httpx.ReadTimeout("Cloud timed out"),
        ]
        res = await router.route_and_optimize(req)

    assert res.tier_used == ModelTier.DETERMINISTIC_OFFLINE
    assert "tier_1_failed -> cascade_to_tier_2" in res.fallback_chain
    assert "tier_2_failed -> cascade_to_tier_3" in res.fallback_chain
    assert res.ast_valid is True
    assert compile(res.optimized_code, "<timeout_patch>", "exec") is not None


@pytest.mark.tier2
@pytest.mark.asyncio
async def test_router_cascades_to_tier3_on_http_500_server_errors(monkeypatch, orphan_actions_pyspark_code):
    """When external providers return HTTP 500, router cascades to Tier 3 deterministic fallback."""
    monkeypatch.setenv("MIDAS_OFFLINE_MODE", "0")
    monkeypatch.setenv("GEMINI_API_KEY", "mock-gemini-key")
    router = DeterministicModelRouter(offline_mode=False)

    req = RefactoringRequest(
        file_path="jobs/500_test.py",
        original_code=orphan_actions_pyspark_code,
        engine="glue",
        offline_only=False,
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [
            httpx.Response(500, text="Internal Server Error in Ollama"),
            httpx.Response(502, text="Bad Gateway in Cloud API"),
        ]
        res = await router.route_and_optimize(req)

    assert res.tier_used == ModelTier.DETERMINISTIC_OFFLINE
    assert "tier_1_failed -> cascade_to_tier_2" in res.fallback_chain
    assert "tier_2_failed -> cascade_to_tier_3" in res.fallback_chain
    assert res.ast_valid is True


@pytest.mark.tier2
@pytest.mark.asyncio
async def test_router_cascades_to_tier3_on_connection_refused(monkeypatch, orphan_actions_pyspark_code):
    """When external provider daemons are not running, router cascades to Tier 3."""
    monkeypatch.setenv("MIDAS_OFFLINE_MODE", "0")
    monkeypatch.setenv("GROQ_API_KEY", "mock-groq-key")
    router = DeterministicModelRouter(offline_mode=False)

    req = RefactoringRequest(
        file_path="jobs/conn_refused.py",
        original_code=orphan_actions_pyspark_code,
        engine="glue",
        offline_only=False,
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [
            httpx.ConnectError("Connection refused by Ollama daemon"),
            httpx.ConnectError("Connection refused by Cloud gateway"),
        ]
        res = await router.route_and_optimize(req)

    assert res.tier_used == ModelTier.DETERMINISTIC_OFFLINE
    assert res.ast_valid is True


# ============================================================================
# 3. Adversarial Edge Cases: Router Failure Modes & Bugs
# ============================================================================


@pytest.mark.tier2
@pytest.mark.asyncio
async def test_cloud_empty_choices_escapes_with_index_error(monkeypatch, orphan_actions_pyspark_code):
    """Adversarial check: When Cloud returns 200 with empty choices list '[]',
    it safely handles missing choices and cascades to Tier 3 without raising IndexError.
    """
    monkeypatch.setenv("MIDAS_OFFLINE_MODE", "0")
    monkeypatch.setenv("GROQ_API_KEY", "mock-groq-key")
    router = DeterministicModelRouter(offline_mode=False)

    req = RefactoringRequest(
        file_path="jobs/empty_choices.py",
        original_code=orphan_actions_pyspark_code,
        engine="glue",
        offline_only=False,
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [
            httpx.ConnectError("Ollama down"),
            httpx.Response(200, json={"choices": []}),  # Empty choices list
        ]
        res = await router.route_and_optimize(req)

    assert res.tier_used == ModelTier.DETERMINISTIC_OFFLINE
    assert res.ast_valid is True


@pytest.mark.tier2
@pytest.mark.asyncio
async def test_ollama_success_crashes_due_to_missing_validate_patch_method(monkeypatch, orphan_actions_pyspark_code):
    """Adversarial check: When Ollama returns 200 with refactored code,
    router validates patch with self.validator.validate and returns LOCAL_LLM tier without AttributeError.
    """
    monkeypatch.setenv("MIDAS_OFFLINE_MODE", "0")
    router = DeterministicModelRouter(offline_mode=False)

    req = RefactoringRequest(
        file_path="jobs/ollama_success.py",
        original_code=orphan_actions_pyspark_code,
        engine="glue",
        offline_only=False,
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(
            200,
            json={"response": "df = spark.read.parquet('s3://data')\ndf.write.parquet('s3://out')\n"},
        )
        res = await router.route_and_optimize(req)

    assert res.tier_used == ModelTier.LOCAL_OLLAMA
    assert res.ast_valid is True
    assert "df.write.parquet" in res.optimized_code
