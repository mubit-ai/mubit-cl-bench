#!/usr/bin/env python3
"""
Analyze and compare CL-Bench results from viewer artifact JSON.gz files.

Usage:
    python scripts/analyze_results.py

Reads all artifacts in results/ and prints a comparison table of normalized
gain, raw gain, stateful/stateless reward, and per-run breakdowns.
"""
from __future__ import annotations

import json
import gzip
import glob
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "results"

# r_max per task (from the CL-Bench paper / task definitions)
R_MAX = {
    "exploitable_poker": 9.4875,
    "database_exploration": 1.0,
    "sales_prediction": 1.0,
    "blind_spectrum_monitoring": 1.0,
    "cohort_studies": 0.162,
    "codebase_adaptation": 1.0,
}


def load_artifact(path: Path) -> dict:
    with gzip.open(path) as f:
        return json.load(f)


def analyze(d: dict, rmax: float) -> dict:
    agg = d["summary"]["aggregate"]
    sf = [x for x in (agg.get("mean_reward_by_index") or []) if x is not None]
    sl = [x for x in (agg.get("baseline_reward_by_index") or []) if x is not None]
    mg = [x for x in (agg.get("mean_gain_by_index") or []) if x is not None]
    rbar_sf = sum(sf) / len(sf) if sf else 0
    rbar_sl = sum(sl) / len(sl) if sl else 0
    denom = rmax - rbar_sl
    gb = (rbar_sf - rbar_sl) / denom if denom != 0 else 0
    runs = d["summary"].get("runs", [])
    run_gains = [round(r["aggregate"].get("total_gain", 0), 2) for r in runs]
    run_rewards = [round(r.get("score", 0), 4) for r in runs]
    model = d["summary"].get("system", {}).get("params", {}).get("model", "?")
    return {
        "gb": gb,
        "raw_gain": sum(mg),
        "r_sf": rbar_sf,
        "r_sl": rbar_sl,
        "run_gains": run_gains,
        "run_rewards": run_rewards,
        "n_runs": len(runs),
        "model": model,
        "mean_gain_by_index": mg,
    }


def fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def main():
    print("=" * 95)
    print("CL-BENCH RESULTS: Mubit Memory System")
    print("=" * 95)

    for task_dir in sorted(RESULTS_DIR.iterdir()):
        if not task_dir.is_dir():
            continue
        task = task_dir.name
        rmax = R_MAX.get(task, 1.0)
        artifacts = sorted(task_dir.glob("*.json.gz"))
        if not artifacts:
            continue

        print(f"\n{'─' * 95}")
        print(f"TASK: {task}  (r_max = {rmax})")
        print(f"{'─' * 95}")
        print(f"  {'Artifact':<35} {'System':<16} {'g_b':>7} {'raw':>7} "
              f"{'r_sf':>7} {'r_sl':>7} {'runs':>5}  Model")
        print(f"  {'─' * 90}")

        for art in artifacts:
            label = art.stem.replace(".json", "")
            try:
                d = load_artifact(art)
                s = analyze(d, rmax)
                system_name = d["summary"].get("system", {}).get("name", "?")
                print(f"  {label:<35} {system_name:<16} {fmt_pct(s['gb']):>7} "
                      f"{s['raw_gain']:>+7.2f} {s['r_sf']:>7.3f} {s['r_sl']:>7.3f} "
                      f"{s['n_runs']:>5}  {s['model']}")

                # Per-run gains
                gains_str = ", ".join(f"{g:+.2f}" for g in s["run_gains"])
                print(f"  {'':>35} {'per-run gains:':<16} [{gains_str}]")

                # Drift analysis for database_exploration
                if task == "database_exploration":
                    mg = s["mean_gain_by_index"]
                    pre = [g for g in mg[:20] if g is not None]
                    post = [g for g in mg[20:] if g is not None]
                    if pre and post:
                        print(f"  {'':>35} {'drift:':<16} "
                              f"pre={sum(pre)/len(pre):+.4f}  "
                              f"post={sum(post)/len(post):+.4f}")
            except Exception as e:
                print(f"  {label:<35} ERROR: {e}")

    print(f"\n{'=' * 95}")
    print("g_b = normalized gain: (r̄_sf − r̄_sl) / (r_max − r̄_sl)")
    print("raw  = cumulative gain: Σ(mean_gain_by_index)")
    print("r_sf = mean stateful reward, r_sl = mean stateless reward")
    print("=" * 95)


if __name__ == "__main__":
    main()
