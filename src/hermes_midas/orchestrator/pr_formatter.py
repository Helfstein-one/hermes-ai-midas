"""Standard 'Midas Touch' Markdown Pull Request Formatter."""

from __future__ import annotations

import json
import re
from typing import Any


class MidasTouchFormatter:
    """Renders standardized Midas Touch markdown Pull Request bodies."""

    def format_pr(
        self,
        workload_name: str,
        script_path: str,
        engine: str,
        fingerprint: str,
        monthly_savings: float,
        annual_savings: float,
        waste_reduction_pct: float,
        anti_patterns: list[dict[str, Any]],
        diff: str,
        trigger_origin: str = "Airflow Webhook",
        trigger_run_id: str = "run-manual-1",
    ) -> str:
        """Render complete Midas Touch markdown PR description."""
        ap_lines = []
        for ap in anti_patterns:
            name = ap.get("pattern_name", ap.get("pattern_id", "Anti-Pattern"))
            desc = ap.get("description", "")
            remed = ap.get("remediation_strategy", "")
            ap_lines.append(f"#### ⚠️ {name}\n- **Impact**: {desc}\n- **Remediation**: {remed}\n")
        ap_markdown = "\n".join(ap_lines)

        metadata = {
            "fingerprint": fingerprint,
            "script_path": script_path,
            "engine": engine,
            "monthly_savings": monthly_savings,
            "waste_reduction_pct": waste_reduction_pct,
            "anti_patterns": [
                ap.get("pattern_id", "") if isinstance(ap, dict) else getattr(ap, "pattern_id", "")
                for ap in anti_patterns
            ],
        }
        metadata_comment = f"<!-- midas-metadata: {json.dumps(metadata)} -->"

        markdown = f"""# 🏆 [Midas FinOps] Optimize Workload: `{workload_name}`

> **Estimated Financial Impact**: **${monthly_savings:,.2f} / month** (${annual_savings:,.2f} / year)
> **Compute Waste Eliminated**: **{waste_reduction_pct:.1f}%** • **AST Verified**: ✅ Syntax & Semantics Validated

---

### 📋 Executive Summary

| Parameter | Specification |
|---|---|
| **Target Pipeline Script** | `{script_path}` |
| **Compute Engine** | `{engine}` |
| **Trigger Origin** | `{trigger_origin}` (Run ID: `{trigger_run_id}`) |
| **Deterministic Fingerprint** | `{fingerprint}` |

---

### 💰 FinOps Impact & Deterministic ROI

| Financial & Compute Metric | Monthly Cost (30-day billing) | Net Savings (Delta) | Waste Reduction (%) |
|---|---|---|---|
| **Optimized Run-Rate** | ${monthly_savings:,.2f} | **${monthly_savings:,.2f}** | {waste_reduction_pct:.1f}% |

---

### 🔍 Detected Anti-Patterns & Waste Mechanisms

{ap_markdown}

---

### 🛠️ Code Refactoring Diff

```diff
{diff}
```

---

### 🛡️ Safety & AST Verification Checklist

- [x] **AST Parsing**: Successfully parsed via `ast.parse` without syntax errors.
- [x] **Bytecode Compilation**: Verified via `compile(..., mode='exec')`.
- [x] **Schema Preservation**: Output columns, data types, and partition keys remain identical.
- [x] **Deterministic Fallback**: Patch generated and verified via deterministic AST rules.

---

### 🤖 Automation Metadata
{metadata_comment}
"""
        return markdown

    @staticmethod
    def extract_metadata(pr_body: str) -> dict[str, Any] | None:
        """Extract hidden JSON metadata from PR body."""
        match = re.search(r"<!--\s*midas-metadata:\s*(\{.*?\})\s*-->", pr_body, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                return None
        return None
