# Project: hermes-ai-midas

## Architecture
Autonomous FinOps & Data Engineering optimization agent powered by FastMCP that monitors ELT workloads, detects compute waste and code anti-patterns, computes deterministic ROI, and opens refactoring Pull Requests.

### High-Level Topology & Data Flow
1. **Triggers**: Inbound HTTP webhook (`/api/v1/triggers/airflow`) or scheduled Cron auditor dispatches pipeline inspection.
2. **Telemetry & Cost Ingestion**: FastMCP tools query CloudWatch (metrics/logs) and AWS Cost Explorer (spending trends, top offenders) via mock or live endpoints.
3. **AST Static Analysis & Code Refactoring**: Analyzes PySpark code to detect anti-patterns (orphan actions, unbroadcasted joins, suboptimal partitions, legacy UDFs). Generates syntax-validated AST patches (`ast.parse` + `compile`).
4. **Deterministic FinOps Calculator**: Calculates exact dollar savings using authoritative cloud rate tables (Glue DPU, EMR Serverless vCPU/GB, Databricks DBU + EC2) with `Decimal` precision.
5. **Multi-Tier Model Router**: Orchestrates patch explanations using Local Ollama (Tier 1) or Free Cloud (Tier 2), seamlessly falling back to Deterministic AST transformations (Tier 3) in offline mode.
6. **PR Creation & Deduplication**: FastMCP Git tool checks for existing open PRs via deterministic fingerprinting and opens a "Midas Touch" refactoring PR on Gitea/GitHub or local filesystem.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Container Orchestration Topology | Podman 5.x & Docker Compose compatible `compose.yaml` (rootless, named volumes, bridge network) | M1 | Survey R1 |
| 2 | Emulated Cloud Services | Moto S3, Glue, CloudWatch metrics/logs & Mock Cost Explorer API | M1 | Survey R1 |
| 3 | Emulated Git & Workflow Platform | Gitea rootless server, Airflow standalone, Ollama container | M1 | Survey R1 |
| 4 | Seed Workload: AWS Glue | `customer360_elt` with orphan actions and legacy Python UDFs ($11,246.40/mo waste) | M1 | Survey R1 |
| 5 | Seed Workload: EMR Serverless | `clickstream_attribution` with unbroadcasted join and micro-partitioning ($303.64/mo waste) | M1 | Survey R1 |
| 6 | Seed Workload: Databricks | `financial_ledger_sync` with skew, spill, and 86% cluster idling ($5,829.60/mo waste) | M1 | Survey R1 |
| 7 | Static AST Orphan Actions Detector | Detects unassigned `.count()`, `.collect()`, `.take()`, `.show()` in PySpark scripts | M2 | Survey R2 |
| 8 | Static AST Unbroadcasted Join Detector | Detects bare dimension table joins lacking `broadcast()` / `F.broadcast()` hints | M2 | Survey R2 |
| 9 | Static AST Suboptimal Partitions Detector | Detects excessive `repartition()`, improper `coalesce()`, missing `partitionBy()` | M2 | Survey R2 |
| 10 | Static AST Legacy UDF Detector | Detects standard Python `@udf` that can be converted to vectorized/native functions | M2 | Survey R2 |
| 11 | Deterministic AST Patch Generator | `NodeTransformer` generating refactored code verified via `ast.parse` and `compile` | M2 | Survey R2 |
| 12 | Deterministic Pricing Tables | Authoritative static rate tables for Glue DPU-hr, EMR Serverless, Databricks DBU | M2 | Survey R2 |
| 13 | Deterministic FinOps Calculator | Exact dollar ROI and percentage compute reduction calculation using `Decimal` | M2 | Survey R2 |
| 14 | FastMCP Cost Explorer Server | `midas-cost-explorer`: top offender retrieval and granular cost breakdowns | M3 | Survey R3 |
| 15 | FastMCP CloudWatch Server | `midas-cloudwatch`: metrics for heap memory, idle time, skew, and GC | M3 | Survey R3 |
| 16 | FastMCP Git Repository Server | `midas-git-repo`: artifact inspection and PR creation across remote REST & local git | M3 | Survey R3 |
| 17 | Multi-Tier Model Router | Tier 1 (Ollama) -> Tier 2 (Free Cloud) -> Tier 3 (Deterministic AST offline fallback) | M4 | Survey R4 |
| 18 | Airflow Webhook Trigger | `/api/v1/triggers/airflow` endpoint handling pipeline completion events | M4 | Survey R4 |
| 19 | Scheduled Cron Auditor | Background workload auditor checking pipelines against waste thresholds | M4 | Survey R4 |
| 20 | PR Deduplication Engine | Deterministic fingerprinting preventing duplicate PRs for the same workload | M4 | Survey R4 |
| 21 | "Midas Touch" PR Generator | Standard markdown PR generator with executive summary, ROI, and code diffs | M4 | Survey R4 |
| 22 | Packaging & Offline Test Infrastructure | `pyproject.toml` with `uv`, pytest runner completely offline without external network | E2E | Acceptance Criteria |
| 23 | E2E Test Suite (Tiers 1-4) | Opaque-box requirement-driven test cases (Feature, Boundary, Combinations, Workloads) | E2E | Acceptance Criteria |
| 24 | E2E Integration Pass (Tiers 1-4) | 100% pass on all E2E test cases under `uv run pytest` | M5 | Acceptance Criteria |
| 25 | Adversarial Coverage Hardening | Tier 5 white-box coverage hardening with adversarial Challenger | M5 | Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E | E2E Testing Track | Offline test infra (`pyproject.toml`, runner) + test cases (Tiers 1-4) -> `TEST_READY.md` | none | PLANNED |
| M1 | Platform Topology & Seed Workloads | `compose.yaml`, mock services, seed data for Glue, EMR, Databricks | none | PLANNED |
| M2 | AST Analysis & FinOps Calculator | PySpark AST visitor/transformer, patch validation, pricing tables, ROI engine | none | PLANNED |
| M3 | FastMCP Tooling Layer | 3 FastMCP servers (Cost Explorer, CloudWatch, Git Repo) with mock/live adapters | M1, M2 | PLANNED |
| M4 | Autonomous Orchestrator & Triggers | Model router, Airflow webhook, Cron auditor, PR deduplication & Midas Touch format | M2, M3 | PLANNED |
| M5 | E2E Integration & Adversarial Hardening | Phase 1: 100% E2E test pass; Phase 2: Tier 5 adversarial hardening | M1, M2, M3, M4, E2E | PLANNED |

## Interface Contracts

### M1 ↔ M3 / M4 (Seed Data & Mock Telemetry)
- File paths: `workloads/glue/customer360_elt.py`, `workloads/emr/clickstream_attribution.py`, `workloads/databricks/financial_ledger_sync.py`
- Manifests: `workloads/<engine>/manifest.json` providing engine metadata, baseline runtime, CPU/RAM, and cost.

### M2 ↔ M3 / M4 (Analysis & Pricing Contracts)
- `ASTInspectionResult`: `file_path: str`, `anti_patterns: list[AntiPatternMatch]`, `patched_code: str`, `is_valid: bool`
- `FinOpsImpact`: `engine: str`, `baseline_cost_usd: Decimal`, `optimized_cost_usd: Decimal`, `monthly_savings_usd: Decimal`, `waste_reduction_pct: Decimal`

### M3 ↔ M4 (FastMCP Tool Interface)
- Cost Explorer: `get_cost_and_usage(start_date, end_date, granularity)`, `get_top_offenders(dimension, limit)`
- CloudWatch: `get_job_telemetry(job_id, engine)`, `get_metric_data(metrics, time_range)`
- Git Repo: `inspect_artifact(repo, path, ref)`, `create_pull_request(repo, title, body, branch, base, changes)`

### M4 ↔ Git / Output
- PR Metadata: fingerprint `SHA256(script_path + ":" + engine + ":" + sorted_anti_patterns)[:16]`
- Markdown Body: Standard "Midas Touch" PR format with FinOps Summary table, Anti-Pattern Breakdown, and Code Diff.

## Code Layout
```
/Users/mauriciohelfstein/dev/hermes-ai-midas/
├── compose.yaml
├── pyproject.toml
├── src/
│   └── hermes_midas/
│       ├── __init__.py
│       ├── topology/              # Mock services and compose helpers
│       ├── ast_analyzer/          # PySpark AST visitors, matchers, patch generator
│       ├── finops/                # Rate tables, pricing calculator, ROI engine
│       ├── mcp_servers/           # FastMCP servers (cost_explorer, cloudwatch, git_repo)
│       ├── router/                # Multi-tier model router (Ollama, cloud, deterministic)
│       ├── orchestrator/          # Webhook triggers, cron auditor, deduplication, PR formatter
│       └── cli.py                 # CLI entry points
├── workloads/                     # Seed workloads & manifests (Glue, EMR, Databricks)
│   ├── glue/
│   ├── emr/
│   └── databricks/
└── tests/                         # Test suites
    ├── conftest.py
    ├── unit/
    ├── e2e/
    └── adversarial/
```
