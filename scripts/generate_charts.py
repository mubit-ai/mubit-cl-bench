#!/usr/bin/env python3
"""
Generate research-grade chart images for the Mubit CL-Bench landing page.

Outputs PNG files at 300 DPI with clean, publication-quality styling.

Usage:
    pip install matplotlib numpy
    python scripts/generate_charts.py
"""
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from pathlib import Path

# Load chart data
REPO = Path(__file__).resolve().parent.parent
with open(REPO / "chart_data.json") as f:
    DATA = json.load(f)

OUTPUT_DIR = REPO / "charts"
OUTPUT_DIR.mkdir(exist_ok=True)

# Publication-quality defaults
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Inter", "Helvetica Neue", "Arial"],
    "font.size": 11,
    "axes.titlesize": 14,
    "axes.titleweight": "bold",
    "axes.labelsize": 12,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 300,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.15,
})

COLORS = {
    "mubit": "#2563eb",
    "mubit_light": "#60a5fa",
    "icl": "#64748b",
    "mem0": "#f59e0b",
    "mem0_light": "#fbbf24",
    "ace": "#ef4444",
    "stateless": "#cbd5e1",
    "grid": "#e2e8f0",
}


def chart_1_gain_comparison():
    """Grouped bar: raw gain across all 6 tasks and systems (keys discovered
    dynamically — rows may carry different system labels and missing entries)."""
    d = DATA["chart_1_normalized_gain_comparison"]
    rows = d["data"]

    # Discover system keys in first-seen order (skip metadata keys).
    systems = []
    for row in rows:
        for k in row:
            if k not in ("task", "note", "mubit_model") and k not in systems:
                systems.append(k)

    def color_for(name):
        n = name.lower()
        if n.startswith("mubit"):
            return COLORS["mubit"]
        if "icl" in n or "notepad" in n or "codex" in n:
            return COLORS["icl"]
        if "mem0" in n:
            return COLORS["mem0"]
        if "ace" in n:
            return COLORS["ace"]
        if "claude" in n:
            return "#7c3aed"
        return "#94a3b8"

    colors = [color_for(s) for s in systems]
    x = np.arange(len(rows))
    width = 0.8 / len(systems)

    fig, ax = plt.subplots(figsize=(14, 6))

    for i, sys_name in enumerate(systems):
        vals = [row.get(sys_name) for row in rows]
        xpos = x + i * width - (len(systems) - 1) * width / 2
        bars = ax.bar(xpos, [v if v is not None else 0 for v in vals], width,
                      label=sys_name, color=colors[i], edgecolor="white", linewidth=0.5)
        for bar, val, v in zip(bars, vals, vals):
            if val is None:
                continue
            # Values are fractions; render as percent.
            yval = bar.get_height()
            va = "bottom" if yval >= 0 else "top"
            offset = 0.008 if yval >= 0 else -0.008
            ax.text(bar.get_x() + bar.get_width() / 2, yval + offset, f"{val*100:+.1f}",
                    ha="center", va=va, fontsize=7.5, fontweight="bold")

    ax.axhline(y=0, color="#475569", linewidth=0.8)
    ax.set_ylabel(d["y_axis"])
    ax.set_title(d["title"], pad=12)
    ax.set_xticks(x)
    labels = [row["task"].replace(" ", "\n", 1) for row in rows]
    ax.set_xticklabels(labels, fontsize=9)
    ax.legend(loc="upper right", frameon=False, fontsize=8.5, ncol=2)
    ax.grid(axis="y", color=COLORS["grid"], linewidth=0.5)
    ax.set_axisbelow(True)

    fig.savefig(OUTPUT_DIR / "chart1_gain_comparison.png", facecolor="white")
    plt.close()
    print("✓ chart1_gain_comparison.png")


def chart_8_sales_model_scaling():
    """Baseline vs stateful across three model tiers + gain annotations."""
    d = DATA["chart_8_sales_model_scaling"]
    rows = d["data"]
    x = np.arange(len(rows))
    width = 0.35

    fig, ax = plt.subplots(figsize=(9, 5.5))
    b1 = ax.bar(x - width / 2, [r["baseline"] for r in rows], width,
                label="Stateless baseline", color=COLORS["stateless"], edgecolor="white")
    b2 = ax.bar(x + width / 2, [r["stateful_mean"] for r in rows], width,
                label="Mubit stateful (mean of 5)", color=COLORS["mubit"], edgecolor="white")

    for xi, r in zip(x, rows):
        ax.errorbar(xi + width / 2, r["stateful_mean"], yerr=r["stateful_std"],
                    fmt="none", ecolor="#1e3a8a", elinewidth=1.4, capsize=4)
        ax.text(xi, max(r["baseline"], r["stateful_mean"]) + 0.045,
                f"gain {r['raw_gain']:+.3f}\nnorm {r['normalized_gain']*100:.0f}%",
                ha="center", fontsize=9, fontweight="bold", color=COLORS["mubit"])

    ax.set_xticks(x)
    ax.set_xticklabels([r["config"] for r in rows], fontsize=10)
    ax.set_ylabel(d["y_axis"])
    ax.set_ylim(0, 1.0)
    ax.set_title(d["title"], pad=12)
    ax.legend(loc="upper left", frameon=False)
    ax.grid(axis="y", color=COLORS["grid"], linewidth=0.5)
    ax.set_axisbelow(True)

    fig.savefig(OUTPUT_DIR / "chart8_sales_model_scaling.png", facecolor="white")
    plt.close()
    print("✓ chart8_sales_model_scaling.png")


def chart_9_cohort_everyone_zero():
    """Dot plot: per-run stateful scores per system; baseline markers; zero line."""
    d = DATA["chart_9_cohort_everyone_zero"]
    rows = d["data"]
    y = np.arange(len(rows))[::-1]

    fig, ax = plt.subplots(figsize=(10, 6.5))

    for yi, r in zip(y, rows):
        name = r["system"]
        is_mubit = name.lower().startswith("mubit")
        base_color = COLORS["mubit"] if is_mubit else COLORS["icl"]
        run_color = COLORS["mubit_light"] if is_mubit else "#94a3b8"

        ax.hlines(yi, min(r["stateful_runs"] + [r["baseline"]]) - 0.004,
                  max(r["stateful_runs"] + [r["baseline"]]) + 0.004,
                  color=COLORS["grid"], linewidth=1, zorder=1)
        ax.scatter([r["baseline"]] * 1, [yi], marker="D", s=55, color="white",
                   edgecolor=base_color, linewidth=1.6, zorder=3,
                   label="Stateless baseline" if yi == y[0] else None)
        ax.scatter(r["stateful_runs"], [yi] * len(r["stateful_runs"]), s=42,
                   color=run_color, edgecolor=base_color, linewidth=0.8, zorder=3,
                   label="Stateful runs" if yi == y[0] else None)
        sig = "n.s." if abs(r["gain"]) < 2 * r["sigma"] else "SIG"
        ax.text(0.075, yi, f"gain {r['gain']:+.3f} ({sig})", fontsize=8.5,
                va="center", color="#475569")

    ax.axvline(x=0, color="#ef4444", linewidth=1.2, linestyle="--", zorder=2)
    ax.text(0.001, len(rows) - 0.35, "zero bits", fontsize=8.5, color="#ef4444")

    ax.set_yticks(y)
    ax.set_yticklabels([r["system"] for r in rows], fontsize=9.5)
    ax.set_xlabel(d["y_axis"])
    ax.set_title(d["title"], pad=12)
    ax.legend(loc="lower left", frameon=False, fontsize=9)
    ax.grid(axis="x", color=COLORS["grid"], linewidth=0.5)
    ax.set_axisbelow(True)

    fig.savefig(OUTPUT_DIR / "chart9_cohort_everyone_zero.png", facecolor="white")
    plt.close()
    print("✓ chart9_cohort_everyone_zero.png")


if __name__ == "__main__":
    print(f"Generating charts to {OUTPUT_DIR}/\n")
    chart_1_gain_comparison()
    chart_2_bsm_learning_curve()
    chart_3_optimization_progression()
    chart_4_per_run_consistency()
    chart_5_drift_adaptation()
    chart_8_sales_model_scaling()
    chart_9_cohort_everyone_zero()
    print(f"\nDone. All charts saved to {OUTPUT_DIR}/")
