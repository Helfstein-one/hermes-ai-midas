"""ASCII comparative bar visualization for terminal benchmarks and resolution demos."""

from __future__ import annotations


def make_bar(value: float, max_value: float, width: int = 20, fill_char: str = "█") -> str:
    """Create a proportional ASCII bar string."""
    if max_value <= 0:
        return fill_char * 0
    ratio = max(0.0, min(1.0, value / max_value))
    bar_len = int(round(ratio * width))
    return fill_char * bar_len


def render_metric_bar(
    metric_name: str,
    baseline: float,
    optimized: float,
    unit: str = "ms",
    width: int = 20,
    is_currency: bool = False,
    speedup_label: bool = False,
) -> str:
    """Renders a 2-line comparative ASCII bar for a given metric (Baseline vs Optimized)."""
    max_val = max(baseline, optimized, 0.0001)
    base_bar = make_bar(baseline, max_val, width=width, fill_char="█")
    opt_bar = make_bar(optimized, max_val, width=width, fill_char="█")

    if is_currency:
        base_val_str = f"${baseline:,.2f}"
        opt_val_str = f"${optimized:,.2f}"
        savings = baseline - optimized
        pct_savings = ((baseline - optimized) / baseline * 100.0) if baseline > 0 else 0.0
        diff_str = f"(-${savings:,.2f} | -{pct_savings:.1f}%)"
    else:
        base_val_str = f"{baseline:.2f} {unit}"
        opt_val_str = f"{optimized:.2f} {unit}"
        if baseline > 0 and optimized > 0:
            speedup = baseline / optimized
            reduction = ((baseline - optimized) / baseline) * 100.0
            if speedup_label:
                diff_str = (
                    f"({speedup:.2f}x faster | -{reduction:.1f}%)"
                    if reduction >= 0
                    else f"({speedup:.2f}x | +{abs(reduction):.1f}%)"
                )
            else:
                diff_str = (
                    f"(-{reduction:.1f}% reduction)" if reduction >= 0 else f"(+{abs(reduction):.1f}% memory buffer)"
                )
        else:
            diff_str = ""

    lines = [
        f"  [{metric_name}]",
        f"    Baseline:  {base_bar:<{width}} {base_val_str:>12}",
        f"    Optimized: {opt_bar:<{width}} {opt_val_str:>12}  {diff_str}",
    ]
    return "\n".join(lines)


def render_resolution_card(
    workload_title: str,
    pattern: str,
    baseline_ms: float,
    optimized_ms: float,
    baseline_mb: float,
    optimized_mb: float,
    baseline_cost: float | None = None,
    optimized_cost: float | None = None,
    parity_ok: bool = True,
    width: int = 22,
) -> str:
    """Render a complete ASCII comparison resolution card for a workload."""
    sep = "=" * 68
    parity_badge = "[✅ 100% DATA PARITY MATCH]" if parity_ok else "[❌ DATA PARITY FAILED]"

    cards = [
        sep,
        f"⚡ RESOLUTION BENCHMARK: {workload_title}",
        f"🎯 Anti-Pattern: {pattern}",
        f"🛡️ Parity Status: {parity_badge}",
        "-" * 68,
        render_metric_bar(
            "Execution Latency",
            baseline=baseline_ms,
            optimized=optimized_ms,
            unit="ms",
            width=width,
            speedup_label=True,
        ),
        "",
        render_metric_bar(
            "Peak Memory (RAM)",
            baseline=baseline_mb,
            optimized=optimized_mb,
            unit="MB",
            width=width,
            speedup_label=False,
        ),
    ]

    if baseline_cost is not None and optimized_cost is not None:
        cards.extend(
            [
                "",
                render_metric_bar(
                    "Monthly Cloud Spend",
                    baseline=baseline_cost,
                    optimized=optimized_cost,
                    unit="USD",
                    width=width,
                    is_currency=True,
                ),
            ]
        )

    cards.append(sep)
    return "\n".join(cards)
