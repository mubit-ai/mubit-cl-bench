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


def chart_2_bsm_learning_curve():
    """Line chart: BSM IoU over 90 scans."""
    d = DATA["chart_2_bsm_learning_curve"]
    x = np.array(d["x_values"])

    fig, ax = plt.subplots(figsize=(11, 5))

    for series in d["series"]:
        y = np.array(series["values"])
        # Smooth with rolling average (window=3) for cleaner curves
        if len(y) > 5:
            kernel = np.ones(3) / 3
            y_smooth = np.convolve(y, kernel, mode="same")
            y_smooth[:2] = y[:2]
            y_smooth[-1] = y[-1]
        else:
            y_smooth = y
        ax.plot(x, y_smooth, color=series["color"], linewidth=2.5,
                label=series["name"], alpha=0.9)
        # Light scatter of raw points
        ax.scatter(x[::5], y[::5], color=series["color"], s=12, alpha=0.4, zorder=3)

    # Stage boundaries
    for boundary in d.get("stage_boundaries", []):
        ax.axvline(x=boundary["x"], color="#cbd5e1", linewidth=1, linestyle="--", alpha=0.7)
        ax.text(boundary["x"] + 0.5, 0.95, boundary["label"], fontsize=7.5,
                color="#64748b", rotation=90, va="top")

    ax.set_xlabel(d["x_axis"])
    ax.set_ylabel(d["y_axis"])
    ax.set_title(d["title"], pad=12)
    ax.set_xlim(1, 90)
    ax.set_ylim(0, 1.05)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(decimals=0))
    ax.legend(loc="lower right", frameon=False)
    ax.grid(True, color=COLORS["grid"], linewidth=0.5)
    ax.set_axisbelow(True)

    fig.savefig(OUTPUT_DIR / "chart2_bsm_learning_curve.png", facecolor="white")
    plt.close()
    print("✓ chart2_bsm_learning_curve.png")


def chart_3_optimization_progression():
    """Bar chart: gain at each optimization stage."""
    d = DATA["chart_3_bsm_optimization_progression"]
    versions = [row["version"] for row in d["data"]]
    gains = [row["gain"] for row in d["data"]]
    ious = [row["iou"] for row in d["data"]]

    x = np.arange(len(versions))
    width = 0.35

    fig, ax1 = plt.subplots(figsize=(9, 5))

    bars1 = ax1.bar(x - width / 2, gains, width, label="Normalized Gain (%)",
                     color=COLORS["mubit"], edgecolor="white", linewidth=0.5)
    bars2 = ax1.bar(x + width / 2, ious, width, label="Spectrum Coverage (IoU %)",
                     color=COLORS["mubit_light"], edgecolor="white", linewidth=0.5)

    for bars in [bars1, bars2]:
        for bar in bars:
            yval = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width() / 2, yval + 1,
                     f"{yval:.1f}%", ha="center", va="bottom", fontsize=9, fontweight="bold")

    ax1.set_ylabel("Percentage")
    ax1.set_title(d["title"], pad=12)
    ax1.set_xticks(x)
    ax1.set_xticklabels(versions, fontsize=9.5)
    ax1.legend(loc="upper left", frameon=False)
    ax1.yaxis.set_major_formatter(mticker.PercentFormatter(decimals=0))
    ax1.grid(axis="y", color=COLORS["grid"], linewidth=0.5)
    ax1.set_axisbelow(True)
    ax1.set_ylim(0, 75)

    fig.savefig(OUTPUT_DIR / "chart3_optimization_progression.png", facecolor="white")
    plt.close()
    print("✓ chart3_optimization_progression.png")


def chart_4_per_run_consistency():
    """Dot plot: per-run IoU showing consistency."""
    d = DATA["chart_4_bsm_per_run_consistency"]["data"]

    fig, ax = plt.subplots(figsize=(8, 4.5))

    categories = []
    values_list = []
    colors_list = []
    baseline_marks = {}

    for name, val in d.items():
        if isinstance(val, list):
            categories.append(name)
            values_list.append(val)
            if "v4" in name:
                colors_list.append(COLORS["mubit"])
            elif "v2" in name:
                colors_list.append(COLORS["mubit_light"])
            else:
                colors_list.append("#94a3b8")
        else:
            baseline_marks[name] = val

    y_positions = range(len(categories))

    for i, (cat, vals, color) in enumerate(zip(categories, values_list, colors_list)):
        # Jitter the x positions slightly for visibility
        x_jitter = [v + np.random.uniform(-0.005, 0.005) for v in vals]
        ax.scatter(x_jitter, [i] * len(vals), color=color, s=80, zorder=3,
                   edgecolors="white", linewidths=0.5)
        # Mean line
        mean_val = np.mean(vals)
        ax.scatter([mean_val], [i], color=color, s=200, marker="|", zorder=4,
                   linewidths=2.5, edgecolors="white")

    # Add baseline reference lines
    for name, val in baseline_marks.items():
        color = "#ef4444" if "ACE" in name else "#f59e0b" if "Mem0" in name else "#64748b"
        ax.axvline(x=val, color=color, linewidth=1, linestyle=":", alpha=0.6)
        ax.text(val, len(categories) - 0.3, name, fontsize=7, color=color,
                ha="center", rotation=90, va="bottom")

    ax.set_yticks(y_positions)
    ax.set_yticklabels(categories, fontsize=10)
    ax.set_xlabel("Spectrum Coverage (IoU)")
    ax.set_title(DATA["chart_4_bsm_per_run_consistency"]["title"], pad=12)
    ax.xaxis.set_major_formatter(mticker.PercentFormatter(decimals=0))
    ax.grid(axis="x", color=COLORS["grid"], linewidth=0.5)
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)

    fig.savefig(OUTPUT_DIR / "chart4_per_run_consistency.png", facecolor="white")
    plt.close()
    print("✓ chart4_per_run_consistency.png")


def chart_5_drift_adaptation():
    """Mubit vs ICL gain either side of the schema migration."""
    d = DATA["chart_5_database_drift_adaptation"]

    fig, ax = plt.subplots(figsize=(10, 5.5))

    # Both series come from artifacts in results/database_exploration (mubit-db-3,
    # icl-db-3). Mem0 used to be plotted here from invented constants — no Mem0 run exists.
    categories = ["Pre-Migration\n(Q1–Q20)", "Post-Migration\n(Q21–Q40)", "Drift Delta\n(change)"]
    mubit_vals = [
        d["pre_migration_gain_mubit"] * 100,
        d["post_migration_gain_mubit"] * 100,
        (d["post_migration_gain_mubit"] - d["pre_migration_gain_mubit"]) * 100,
    ]
    icl_vals = [
        d["pre_migration_gain_icl"] * 100,
        d["post_migration_gain_icl"] * 100,
        (d["post_migration_gain_icl"] - d["pre_migration_gain_icl"]) * 100,
    ]

    x = np.arange(len(categories))
    width = 0.35

    bars_m = ax.bar(x - width/2, mubit_vals, width, color=COLORS["mubit"],
                    label="Mubit", edgecolor="white", linewidth=0.5)
    bars_e = ax.bar(x + width/2, icl_vals, width, color=COLORS["icl"],
                    label="ICL", edgecolor="white", linewidth=0.5)

    # Value labels
    for bar, val in zip(bars_m, mubit_vals):
        va = "bottom" if val >= 0 else "top"
        offset = 0.5 if val >= 0 else -0.5
        ax.text(bar.get_x() + bar.get_width()/2, val + offset,
                f"{val:+.1f}%", ha="center", va=va, fontsize=10, fontweight="bold",
                color=COLORS["mubit"])
    for bar, val in zip(bars_e, icl_vals):
        va = "bottom" if val >= 0 else "top"
        offset = 0.5 if val >= 0 else -0.5
        ax.text(bar.get_x() + bar.get_width()/2, val + offset,
                f"{val:+.1f}%", ha="center", va=va, fontsize=10, fontweight="bold",
                color=COLORS["icl"])

    ax.axhline(y=0, color="#475569", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(categories, fontsize=11)
    ax.set_ylabel(d["y_axis"])
    ax.set_title(d["title"], pad=12, fontsize=14, fontweight="bold")
    ax.legend(frameon=False, fontsize=11, loc="upper right")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(decimals=0))
    ax.grid(axis="y", color=COLORS["grid"], linewidth=0.5)
    ax.set_axisbelow(True)

    fig.savefig(OUTPUT_DIR / "chart5_drift_adaptation.png", facecolor="white")
    plt.close()
    print("✓ chart5_drift_adaptation.png")


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
