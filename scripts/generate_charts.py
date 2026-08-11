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
    "ace": "#ef4444",
    "stateless": "#cbd5e1",
    "grid": "#e2e8f0",
}


def chart_1_gain_comparison():
    """Grouped bar: normalized gain across tasks and systems."""
    d = DATA["chart_1_normalized_gain_comparison"]
    tasks = [row["task"] for row in d["data"]]
    systems = ["Mubit", "ICL (GPT-5.4)", "Mem0 (GPT-5.4)", "ACE (GPT-5.4)"]
    colors = [COLORS["mubit"], COLORS["icl"], COLORS["mem0"], COLORS["ace"]]

    x = np.arange(len(tasks))
    width = 0.18

    fig, ax = plt.subplots(figsize=(10, 5.5))

    for i, (sys_name, color) in enumerate(zip(systems, colors)):
        vals = [row[sys_name] for row in d["data"]]
        bars = ax.bar(x + i * width - 1.5 * width, vals, width, label=sys_name, color=color, edgecolor="white", linewidth=0.5)
        for bar, val in zip(bars, vals):
            yval = bar.get_height()
            va = "bottom" if yval >= 0 else "top"
            offset = 0.5 if yval >= 0 else -0.5
            ax.text(bar.get_x() + bar.get_width() / 2, yval + offset, f"{val:+.1f}%",
                    ha="center", va=va, fontsize=8.5, fontweight="bold")

    ax.axhline(y=0, color="#475569", linewidth=0.8)
    ax.set_ylabel(d["y_axis"])
    ax.set_title(d["title"], pad=12)
    ax.set_xticks(x)
    ax.set_xticklabels(tasks, fontsize=10)
    ax.legend(loc="upper right", frameon=False, fontsize=9)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(decimals=0))
    ax.grid(axis="y", color=COLORS["grid"], linewidth=0.5)
    ax.set_axisbelow(True)

    fig.savefig(OUTPUT_DIR / "chart1_gain_comparison.png", facecolor="white")
    plt.close()
    print("✓ chart1_gain_comparison.png")


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
    """Line chart: DB exploration gain pre/post migration."""
    d = DATA["chart_5_database_drift_adaptation"]

    fig, ax = plt.subplots(figsize=(8, 4.5))

    # Pre-migration
    ax.bar([0], [d["pre_migration_gain_mubit"]], 0.4, color=COLORS["mubit"],
           label=f"Mubit: {d['pre_migration_gain_mubit']:+.4f}", edgecolor="white")
    ax.bar([1], [d["post_migration_gain_mubit"]], 0.4, color=COLORS["mubit_light"],
           label=f"Mubit: {d['post_migration_gain_mubit']:+.4f}", edgecolor="white")
    ax.bar([2], [d["pre_migration_gain_icl"]], 0.4, color=COLORS["icl"],
           label=f"ICL: {d['pre_migration_gain_icl']:+.4f}", edgecolor="white", alpha=0.6)
    ax.bar([3], [d["post_migration_gain_icl"]], 0.4, color="#cbd5e1",
           label=f"ICL: {d['post_migration_gain_icl']:+.4f}", edgecolor="white", alpha=0.6)

    ax.set_xticks([0, 1, 2, 3])
    ax.set_xticklabels(["Mubit\nPre-migration", "Mubit\nPost-migration",
                         "ICL\nPre-migration", "ICL\nPost-migration"], fontsize=9)
    ax.set_ylabel("Mean Gain per Question")
    ax.set_title(d["title"], pad=12)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    ax.grid(axis="y", color=COLORS["grid"], linewidth=0.5)
    ax.set_axisbelow(True)

    # Add annotation
    ax.annotate("+32% gain increase\nafter schema drift",
                xy=(1, d["post_migration_gain_mubit"]),
                xytext=(2.5, d["post_migration_gain_mubit"] + 0.03),
                fontsize=9, fontweight="bold", color=COLORS["mubit"],
                arrowprops=dict(arrowstyle="->", color=COLORS["mubit"], lw=1.5))

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
    print(f"\nDone. All charts saved to {OUTPUT_DIR}/")
