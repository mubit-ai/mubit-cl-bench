#!/usr/bin/env python3
"""
Extract chart-ready data from CL-Bench viewer artifacts, and verify
DEMO_DATA_REPORT.md against the artifacts before writing anything.

This is the single place any number is computed. `chart_data.json` and the
report's tables are checked AGAINST this script's output; they are never read
as inputs to a chart.

Usage:
    python3 scripts/extract.py            # verify + write viz_data/
    python3 scripts/extract.py --verify   # verify only, write nothing

Stdlib only — no install step.
"""
from __future__ import annotations

import gzip
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "results"
OUT_DIR = REPO_ROOT / "viz_data"

# r_max per task (from the CL-Bench paper / task definitions).
# Matches scripts/analyze_results.py so the two agree by construction.
R_MAX = {
    "exploitable_poker": 9.4875,
    "database_exploration": 1.0,
    "blind_spectrum_monitoring": 1.0,
}

# Index at which database_exploration's schema migration lands.
DB_DRIFT_INDEX = 20

# Frequency band for blind_spectrum_monitoring, in MHz.
BSM_BAND = (0.0, 168.0)


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------

def load_artifact(path: Path) -> dict:
    with gzip.open(path) as f:
        return json.load(f)


def discover() -> list[tuple[str, str, Path]]:
    """Return (task, artifact_id, path) for every artifact on disk."""
    found = []
    for task_dir in sorted(RESULTS_DIR.iterdir()):
        if not task_dir.is_dir():
            continue
        for p in sorted(task_dir.glob("*.json.gz")):
            found.append((task_dir.name, p.name[: -len(".json.gz")], p))
    return found


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


# --------------------------------------------------------------------------
# core derivation — every headline number comes from here
# --------------------------------------------------------------------------

def derive(task: str, artifact_id: str, d: dict) -> dict:
    summary = d["summary"]
    agg = summary["aggregate"]
    rmax = R_MAX.get(task, 1.0)

    sf_series = agg.get("mean_reward_by_index") or []
    sl_series = agg.get("baseline_reward_by_index") or []
    gain_series = agg.get("mean_gain_by_index") or []

    r_sf = mean(sf_series) or 0.0
    r_sl = mean(sl_series) or 0.0
    denom = rmax - r_sl
    g_b = (r_sf - r_sl) / denom if denom else 0.0

    runs = []
    for r in summary.get("runs", []):
        ra = r.get("aggregate", {})
        runs.append({
            "run_index": r.get("run_index"),
            "score": r.get("score"),
            "total_gain": ra.get("total_gain"),
            "mean_reward": ra.get("mean_reward"),
            "reward_by_index": ra.get("reward_by_index") or [],
            "gain_by_index": ra.get("gain_by_index") or [],
            "cost_by_index": ra.get("cost_by_index") or [],
        })

    # aggregate.metrics is {name: {mean,std,min,max}} — flatten to the mean,
    # keeping std/min/max alongside for the dot plots.
    metrics = {}
    for k, v in (agg.get("metrics") or {}).items():
        if isinstance(v, dict) and "mean" in v:
            metrics[k] = {
                "mean": v.get("mean"), "std": v.get("std"),
                "min": v.get("min"), "max": v.get("max"),
            }

    # per-run respond usage, and the baseline's
    def usage_of(trace):
        u = ((trace.get("execution") or {}).get("usage") or {}).get("respond") or {}
        return {
            "call_count": u.get("call_count"),
            "input_tokens": u.get("input_tokens"),
            "output_tokens": u.get("output_tokens"),
            "reasoning_tokens": u.get("reasoning_tokens"),
            "cost_usd": u.get("cost_usd"),
        }

    run_usage = [usage_of(rt["trace"]) for rt in d.get("run_traces", [])]
    baseline_usage = usage_of(d.get("baseline_trace") or {})

    def wall_of(trace):
        e = trace.get("execution") or {}
        return {
            "wall_duration_seconds": e.get("wall_duration_seconds"),
            "avg_response_seconds": e.get("avg_response_seconds"),
            "max_response_seconds": e.get("max_response_seconds"),
            "total_interactions": e.get("total_interactions"),
        }

    run_wall = [wall_of(rt["trace"]) for rt in d.get("run_traces", [])]
    baseline_wall = wall_of(d.get("baseline_trace") or {})

    # Cost is emitted as literal 0 (not null) on gemini-3.5-flash artifacts.
    # A zero plots as "free", so flag it rather than letting a chart show it.
    all_cost = [u["cost_usd"] for u in run_usage if u["cost_usd"] is not None]
    cost_reliable = bool(all_cost) and any(c > 0 for c in all_cost)

    total_interactions = sum(
        len(rt["trace"].get("interactions") or []) for rt in d.get("run_traces", [])
    ) + len((d.get("baseline_trace") or {}).get("interactions") or [])

    model = (summary.get("system", {}).get("params", {}) or {}).get("model")
    schedule = summary.get("schedule")

    return {
        "id": artifact_id,
        "task": task,
        "system": summary.get("system", {}).get("name"),
        "model": model,
        "schedule": schedule,
        # Two artifacts are only comparable if task, schedule AND model match.
        "comparability_key": f"{task}|{schedule}|{model}",
        "r_max": rmax,
        "n_instances": len(sf_series),
        "n_runs": len(runs),
        "g_b": g_b,
        "raw_gain": sum(x for x in gain_series if x is not None),
        "r_sf": r_sf,
        "r_sl": r_sl,
        "final_cumulative_mean_gain": agg.get("final_cumulative_mean_gain"),
        "series": {
            "baseline_reward_by_index": sl_series,
            "mean_reward_by_index": sf_series,
            "mean_gain_by_index": gain_series,
            "cumulative_mean_gain_by_index": agg.get("cumulative_mean_gain_by_index") or [],
            "mean_latency_by_index": agg.get("mean_latency_by_index") or [],
            "mean_cost_by_index": agg.get("mean_cost_by_index") or [],
            "mean_raw_metric_by_index": agg.get("mean_raw_metric_by_index") or [],
        },
        "raw_metric_name": agg.get("raw_metric_name"),
        "task_params": summary.get("task", {}).get("params", {}),
        "runs": runs,
        "metrics": metrics,
        "usage": {"runs": run_usage, "baseline": baseline_usage,
                  "cost_reliable": cost_reliable},
        "wall": {"runs": run_wall, "baseline": baseline_wall},
        "total_interactions": total_interactions,
        "system_memory_present": any(
            rt["trace"].get("system_memory") is not None for rt in d.get("run_traces", [])
        ),
    }


# --------------------------------------------------------------------------
# task-specific extraction
# --------------------------------------------------------------------------

def intervals(checks, kind):
    """checks[] entries are center_freq/bandwidth — convert to [lo, hi] MHz."""
    out = []
    for c in checks or []:
        if c.get("type") != kind:
            continue
        cf, bw = c.get("center_freq"), c.get("bandwidth")
        if cf is None or bw is None:
            continue
        out.append([round(cf - bw / 2, 4), round(cf + bw / 2, 4)])
    out.sort()
    return out


def scan_record(sr):
    sc = sr.get("scoring") or {}
    checks = sc.get("checks") or []
    tx = [[t.get("center_freq"), t.get("bandwidth"), t.get("estimated_power")]
          for t in ((sr.get("report") or {}).get("transmitters") or [])]
    return {
        "scan_idx": sr.get("scan_idx"),
        "score": sc.get("score"),
        "n_gt": sc.get("n_gt"),
        "n_reported": sc.get("n_reported"),
        "n_matched": sc.get("n_matched"),
        "gt": intervals(checks, "gt_available"),
        "rep": intervals(checks, "reported_available"),
        "ovl": intervals(checks, "overlap"),
        "tx": tx,
        "unsafe_bw": sc.get("unsafe_bandwidth_claimed"),
        "missed_bw": sc.get("missed_available_bandwidth"),
        "gt_bw": sc.get("gt_available_bandwidth"),
        "rep_bw": sc.get("reported_available_bandwidth"),
        "ovl_bw": sc.get("overlap_bandwidth"),
    }


def extract_bsm(d: dict) -> dict:
    """Per-scan spectrum geometry for the stateful runs AND the stateless baseline.

    The baseline stores one scan per instance_trace rather than a single
    scan_results list, so it has to be stitched back together by scan_idx.
    """
    out = {"band": list(BSM_BAND), "runs": [], "baseline": None}

    for rt in d.get("run_traces", []):
        tr = rt["trace"]
        m = (tr.get("result") or {}).get("metrics") or {}
        scans = [scan_record(sr) for sr in (m.get("scan_results") or [])]
        reg, peaks = [], []
        for it in tr.get("interactions") or []:
            md = (it.get("response") or {}).get("metadata") or {}
            reg.append(md.get("registry_size"))
            peaks.append(md.get("scan_peaks"))
        out["runs"].append({
            "scans": scans,
            "registry_size": reg,
            "scan_peaks": peaks,
            "reported_per_scan": [len(s["tx"]) for s in scans],
            "score_curve": m.get("score_curve") or [],
            "first_half_score": m.get("first_half_score"),
            "second_half_score": m.get("second_half_score"),
            "learning_delta": m.get("learning_delta"),
        })

    bt = d.get("baseline_trace") or {}
    # NB: scan_idx is 0 on every baseline sub-trace (each knows only its own
    # scan), so it cannot order these. instance_traces order is the ordering;
    # verify() checks it elementwise against baseline_reward_by_index.
    b_scans = []
    for i, itr in enumerate(bt.get("instance_traces") or []):
        m = (itr.get("result") or {}).get("metrics") or {}
        for sr in (m.get("scan_results") or []):
            rec = scan_record(sr)
            rec["scan_idx"] = i
            b_scans.append(rec)
    b_reg, b_peaks = [], []
    for it in bt.get("interactions") or []:
        md = (it.get("response") or {}).get("metadata") or {}
        b_reg.append(md.get("registry_size"))
        b_peaks.append(md.get("scan_peaks"))
    # The baseline's per-interaction action is the authoritative report count;
    # instance_traces and interactions are in the same scan order.
    b_reported = []
    for it in bt.get("interactions") or []:
        tx = ((it.get("response") or {}).get("action") or {}).get("transmitters")
        b_reported.append(len(tx) if isinstance(tx, list) else None)
    out["baseline"] = {
        "scans": b_scans,
        "registry_size": b_reg,
        "scan_peaks": b_peaks,
        "reported_per_scan": b_reported,
    }
    return out


def extract_db(d: dict) -> dict:
    """Question outcomes per run, plus per-step context growth."""
    out = {"questions": None, "runs": [], "baseline": None}

    for rt in d.get("run_traces", []):
        tr = rt["trace"]
        m = (tr.get("result") or {}).get("metrics") or {}
        qh = m.get("question_history") or []

        # Question text/ground truth is identical across runs — store once.
        if out["questions"] is None and qh:
            out["questions"] = [{
                "question_id": q.get("question_id"),
                "question": q.get("question"),
                "difficulty": q.get("difficulty"),
                "ground_truth": q.get("ground_truth"),
            } for q in qh]

        out["runs"].append({
            "outcomes": [{
                "correct": q.get("correct"),
                "num_queries": q.get("num_queries"),
                "num_actions": q.get("num_actions"),
                "regret": q.get("regret"),
                "submitted_answer": q.get("submitted_answer"),
                "timed_out": q.get("timed_out"),
                "budget_exceeded": q.get("budget_exceeded"),
            } for q in qh],
            "steps": step_series(tr),
            "accuracy": m.get("accuracy"),
            "avg_queries_per_question": m.get("avg_queries_per_question"),
            "first_half_accuracy": m.get("first_half_accuracy"),
            "second_half_accuracy": m.get("second_half_accuracy"),
            "cumulative_regret": m.get("cumulative_regret"),
            "variant_id": m.get("variant_id"),
            "variant_display_name": m.get("variant_display_name"),
        })

    bt = d.get("baseline_trace") or {}
    out["baseline"] = {"steps": step_series(bt),
                       "outcomes": baseline_per_instance(bt, "question_history", [
                           "correct", "num_queries", "num_actions", "regret",
                           "submitted_answer", "timed_out", "budget_exceeded"])}
    return out


def baseline_per_instance(bt: dict, list_key: str, fields: list[str]) -> list:
    """Rebuild the baseline's per-instance record.

    `baseline_trace.result.metrics` is empty in every artifact, but each
    `instance_traces[i]` carries its own single-instance metrics block. This is
    the only way to get the stateless run's per-instance detail.

    ORDERING: the natural-looking sort keys are useless here. Each sub-trace
    only knows about its own instance, so `scan_idx` is 0 on all 90 BSM entries
    and `hand_num` is 1 on all 120 poker entries. Sorting by them is a no-op
    that merely preserves list order by stable-sort accident. The real ordering
    is `instance_traces` order itself, which `verify()` checks elementwise
    against `baseline_reward_by_index` rather than assuming.
    """
    out = []
    for i, itr in enumerate(bt.get("instance_traces") or []):
        m = (itr.get("result") or {}).get("metrics") or {}
        for rec in (m.get(list_key) or []):
            row = {f: rec.get(f) for f in fields}
            row["instance_index"] = i
            out.append(row)
    return out


def step_series(trace: dict) -> dict:
    """Per-step token/latency/memory signals — the context-growth evidence.

    ICL reports its own `context_tokens`; memory systems don't, so the
    comparable quantity is the actual prompt size, usage.respond.input_tokens.
    """
    ctx, inp, out_t, lat, retr, qnum, distinct = [], [], [], [], [], [], []
    seen = set()
    for it in trace.get("interactions") or []:
        md = (it.get("response") or {}).get("metadata") or {}
        u = ((it.get("usage") or {}).get("respond")) or {}
        t = it.get("timing") or {}
        qm = it.get("query", {}).get("metadata") or {}

        ctx.append(md.get("context_tokens"))
        inp.append(u.get("input_tokens"))
        out_t.append(u.get("output_tokens"))
        lat.append(t.get("response_latency_seconds"))
        retr.append(md.get("retrieved_count"))
        qnum.append(qm.get("question_num") or qm.get("hand_num"))

        for lm in (md.get("retrieved_lessons_meta") or []):
            if lm.get("id"):
                seen.add(lm["id"])
        distinct.append(len(seen))

    return {
        "context_tokens": ctx if any(x is not None for x in ctx) else [],
        "input_tokens": inp,
        "output_tokens": out_t,
        "latency_seconds": lat,
        "retrieved_count": retr if any(x is not None for x in retr) else [],
        "instance_num": qnum,
        "distinct_lessons": distinct if seen else [],
    }


def extract_poker(d: dict) -> dict:
    """Hand-by-hand profit with the opponent-regime label on every hand."""
    out = {"runs": [], "baseline": None}
    for rt in d.get("run_traces", []):
        tr = rt["trace"]
        m = (tr.get("result") or {}).get("metrics") or {}
        hh = m.get("hand_history") or []
        out["runs"].append({
            "hands": [{
                "hand_num": h.get("hand_num"),
                "profit": h.get("profit"),
                "total_profit": h.get("total_profit"),
                "variant_id": h.get("variant_id"),
                "n_actions": len(h.get("actions") or []),
            } for h in hh],
            "steps": step_series(tr),
            "total_profit": m.get("total_profit"),
            "avg_profit_per_hand": m.get("avg_profit_per_hand"),
            "bb_per_hand": m.get("bb_per_hand"),
            "first_half_avg": m.get("first_half_avg"),
            "second_half_avg": m.get("second_half_avg"),
            "variant_id": m.get("variant_id"),
        })
    bt = d.get("baseline_trace") or {}
    bhh = baseline_per_instance(bt, "hand_history",
                                ["hand_num", "profit", "total_profit", "variant_id"])
    # hand_num is 1 on every entry — do NOT sort or plot against it. Order is
    # instance_traces order, checked in verify().
    # The baseline resets every hand, so each sub-trace reports total_profit for
    # its own hand alone. Re-cumulate so the curve is comparable to a run's.
    running = 0
    for h in bhh:
        running += h.get("profit") or 0
        h["cumulative_profit"] = running
    out["baseline"] = {"hands": bhh, "steps": step_series(bt)}
    return out


# --------------------------------------------------------------------------
# verification — every claim in DEMO_DATA_REPORT.md §6/§7/§11 that is
# derivable from the artifacts, re-derived and compared.
# --------------------------------------------------------------------------

class Checks:
    def __init__(self):
        self.rows = []

    def add(self, section, claim, expected, actual, tol=0.0, unit=""):
        if expected is None or actual is None:
            status = "NO DATA"
            delta = None
        elif isinstance(expected, (list, tuple)):
            ok = (len(expected) == len(actual)
                  and all(abs(e - a) <= tol for e, a in zip(expected, actual)))
            status = "PASS" if ok else "MISMATCH"
            delta = None
        elif isinstance(expected, bool) or isinstance(actual, bool):
            status = "PASS" if bool(expected) == bool(actual) else "MISMATCH"
            delta = None
        elif isinstance(expected, str) or isinstance(actual, str):
            status = "PASS" if str(expected) == str(actual) else "MISMATCH"
            delta = None
        else:
            delta = actual - expected
            status = "PASS" if abs(delta) <= tol else "MISMATCH"
        self.rows.append({
            "section": section, "claim": claim,
            "expected": expected, "actual": actual,
            "delta": delta, "status": status, "unit": unit,
        })

    def counts(self):
        c = {"PASS": 0, "MISMATCH": 0, "NO DATA": 0}
        for r in self.rows:
            c[r["status"]] = c.get(r["status"], 0) + 1
        return c


def fmt_val(v, unit=""):
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(f"{x:+.2f}" for x in v) + "]"
    if isinstance(v, float):
        return f"{v:,.4f}{unit}" if abs(v) < 1000 else f"{v:,.0f}{unit}"
    return f"{v}{unit}"


def verify(derived: dict, bsm: dict, db: dict, poker: dict) -> Checks:
    c = Checks()
    g = derived.get

    # ---- §6 headline table: g_b / raw / r_sf / r_sl for all 12 -------------
    # (expected values transcribed from DEMO_DATA_REPORT.md §6)
    hl = {
        "mubit-bsm-3.5flash":            (0.116, 8.14, 0.310, 0.220),
        "mubit-bsm-registry-3.5flash":   (0.318, 15.19, 0.638, 0.470),
        "mubit-bsm-v4-3.5flash":         (0.537, 36.92, 0.647, 0.237),
        "icl-db-3":                      (0.114, 4.40, 0.145, 0.035),
        "mubit-db-3":                    (0.137, 5.20, 0.180, 0.050),
        "mubit-full-db-3":               (0.118, 4.40, 0.182, 0.072),
        "mubit-genai-db-3":              (0.019, 0.71, 0.089, 0.072),
        "mubit-genai-db-full-3.5flash":  (0.011, 0.40, 0.070, 0.060),
        "mubit-quick-3":                 (0.075, 3.83, -0.033, -0.800),
        "icl-quick-3":                   (0.017, 0.83, -0.433, -0.600),
        "mubit-poker-v5-3.5flash":       (-0.010, -10.63, 0.297, 0.386),
        "mubit-poker-full-3.5flash":     (-0.014, -15.00, 0.175, 0.300),
    }
    for aid, (e_gb, e_raw, e_sf, e_sl) in hl.items():
        a = g(aid)
        if not a:
            c.add("§6", f"{aid} exists", True, False)
            continue
        c.add("§6", f"{aid} g_b", e_gb, a["g_b"], tol=0.0006)
        c.add("§6", f"{aid} raw Σgain", e_raw, a["raw_gain"], tol=0.006)
        c.add("§6", f"{aid} r_sf", e_sf, a["r_sf"], tol=0.0006)
        c.add("§6", f"{aid} r_sl", e_sl, a["r_sl"], tol=0.0006)

    # ---- §6 BSM per-run scores / halves ----------------------------------
    v4 = g("mubit-bsm-v4-3.5flash")
    if v4:
        c.add("§6", "BSM v4 per-run IoU", [0.6022, 0.6871, 0.6512],
              [r["score"] for r in v4["runs"]], tol=0.0002)
        c.add("§6", "BSM v4 first_half_score", 0.544,
              (v4["metrics"].get("first_half_score") or {}).get("mean"), tol=0.001)
        c.add("§6", "BSM v4 second_half_score", 0.7497,
              (v4["metrics"].get("second_half_score") or {}).get("mean"), tol=0.001)
        c.add("§6", "BSM v4 learning_delta", 0.2057,
              (v4["metrics"].get("learning_delta") or {}).get("mean"), tol=0.001)

    # ---- §6 DB task-quality metrics --------------------------------------
    qual = {
        "icl-db-3":                     (0.1917, 3.225, 0.150, 0.2333, 513.0),
        "mubit-db-3":                   (0.3167, 6.85, 0.2833, 0.350, 492.0),
        "mubit-full-db-3":              (0.3333, 7.29, 0.300, 0.3667, 491.0),
        "mubit-genai-db-3":             (0.6667, 13.51, 0.7167, 0.6167, 546.3),
        "mubit-genai-db-full-3.5flash": (0.7167, 13.62, 0.7667, 0.6667, 558.0),
    }
    for aid, (acc, q, h1, h2, reg) in qual.items():
        a = g(aid)
        if not a:
            continue
        m = a["metrics"]
        c.add("§6", f"{aid} accuracy", acc, (m.get("accuracy") or {}).get("mean"), tol=0.001)
        c.add("§6", f"{aid} avg queries/Q", q,
              (m.get("avg_queries_per_question") or {}).get("mean"), tol=0.01)
        c.add("§6", f"{aid} 1st-half acc", h1,
              (m.get("first_half_accuracy") or {}).get("mean"), tol=0.001)
        c.add("§6", f"{aid} 2nd-half acc", h2,
              (m.get("second_half_accuracy") or {}).get("mean"), tol=0.001)
        c.add("§6", f"{aid} cumulative_regret", reg,
              (m.get("cumulative_regret") or {}).get("mean"), tol=0.1)

    # ---- §6 cost / token table (2.5-flash DB only) -----------------------
    cost = {
        "mubit-db-3":      (314.0, 3226824, 189471, 1.073),
        "icl-db-3":        (169.0, 6396228, 219739, 1.113),
        "mubit-full-db-3": (331.7, 3670429, 217802, 1.249),
    }
    for aid, (calls, inp, outp, usd) in cost.items():
        a = g(aid)
        if not a:
            continue
        ru = a["usage"]["runs"]
        c.add("§6", f"{aid} mean respond calls", calls,
              mean([u["call_count"] for u in ru]), tol=0.1)
        c.add("§6", f"{aid} mean input tokens", float(inp),
              mean([u["input_tokens"] for u in ru]), tol=1.0)
        c.add("§6", f"{aid} mean output tokens", float(outp),
              mean([u["output_tokens"] for u in ru]), tol=1.0)
        c.add("§6", f"{aid} mean cost USD", usd,
              mean([u["cost_usd"] for u in ru]), tol=0.001)

    # ---- §7.1 the BSM headline is a baseline artifact ---------------------
    v2 = g("mubit-bsm-registry-3.5flash")
    if v2 and v4:
        c.add("§7.1", "v2 r_sf", 0.6385, v2["r_sf"], tol=0.0002)
        c.add("§7.1", "v4 r_sf", 0.6468, v4["r_sf"], tol=0.0002)
        c.add("§7.1", "v2 r_sl", 0.4697, v2["r_sl"], tol=0.0002)
        c.add("§7.1", "v4 r_sl", 0.2366, v4["r_sl"], tol=0.0002)
        b2 = bsm["mubit-bsm-registry-3.5flash"]["baseline"]
        b4 = bsm["mubit-bsm-v4-3.5flash"]["baseline"]
        c.add("§7.1", "v2 baseline reported tx/scan", 8.11,
              mean(b2["reported_per_scan"]), tol=0.01)
        c.add("§7.1", "v4 baseline reported tx/scan", 3.31,
              mean(b4["reported_per_scan"]), tol=0.01)
        c.add("§7.1", "v2 baseline max IoU", 1.000,
              max(x for x in v2["series"]["baseline_reward_by_index"] if x is not None),
              tol=0.001)
        c.add("§7.1", "v4 baseline max IoU", 0.320,
              max(x for x in v4["series"]["baseline_reward_by_index"] if x is not None),
              tol=0.001)

    # ---- §7.3 chart_data.json duplicates competitor values ---------------
    cd_path = REPO_ROOT / "chart_data.json"
    if cd_path.exists():
        cd = json.loads(cd_path.read_text())
        rows = {r["task"]: r for r in cd["chart_1_normalized_gain_comparison"]["data"]}
        dbr, pkr = rows.get("Database Exploration"), rows.get("Exploitable Poker")
        if dbr and pkr:
            dup = all(dbr.get(k) == pkr.get(k)
                      for k in ("ICL (GPT-5.4)", "Mem0 (GPT-5.4)", "ACE (GPT-5.4)"))
            c.add("§7.3", "DB and Poker competitor rows identical", True, dup)

        # ---- §7.4 README vs chart_data disagree on poker -----------------
        c.add("§7.4", "chart_data poker Mubit g_b", -1.0,
              float(pkr.get("Mubit")) if pkr else None, tol=0.05, unit="%")
        readme = (REPO_ROOT / "README.md").read_text() if (REPO_ROOT / "README.md").exists() else ""
        c.add("§7.4", "README states poker 7.5%", True, bool(re.search(r"7\.5\s*%", readme)))
        mq = g("mubit-quick-3")
        c.add("§7.4", "5-hand g_b (quick_test)", 0.075, mq["g_b"] if mq else None, tol=0.001)

        # ---- §7.6 chart_6 ICL db_efficiency vs artifact ------------------
        ch6 = next((v for k, v in cd.items() if k.startswith("chart_6")), {})
        by_sys = {r.get("system"): r for r in (ch6.get("data") or [])}
        c.add("§7.6", "chart_data ICL db_efficiency", "17%",
              (by_sys.get("ICL") or {}).get("db_efficiency"))
        icl = g("icl-db-3")
        c.add("§7.6", "icl-db-3 actual r_sf (=14.5%, not 17%)", 0.145,
              icl["r_sf"] if icl else None, tol=0.001)
        c.add("§7.6", "chart_data Mubit db_efficiency", "18%",
              (by_sys.get("Mubit") or {}).get("db_efficiency"))
        md = g("mubit-db-3")
        c.add("§7.6", "mubit-db-3 actual r_sf (18% is correct)", 0.180,
              md["r_sf"] if md else None, tol=0.001)
        c.add("§7.6", "chart_data Mubit bsm_iou", "65%",
              (by_sys.get("Mubit") or {}).get("bsm_iou"))
        c.add("§7.6", "BSM v4 actual r_sf (65% is correct)", 0.647,
              v4["r_sf"] if v4 else None, tol=0.001)

    # ---- §7.5 drift favours ICL ------------------------------------------
    for aid, e_pre, e_post, e_slpre, e_slpost in [
        ("mubit-db-3", 0.1122, 0.1478, 0.0533, 0.0467),
        ("icl-db-3", 0.0844, 0.1355, 0.0233, 0.0467),
    ]:
        a = g(aid)
        if not a:
            continue
        mg = a["series"]["mean_gain_by_index"]
        sl = a["series"]["baseline_reward_by_index"]
        c.add("§7.5", f"{aid} pre-drift mean gain", e_pre,
              mean(mg[:DB_DRIFT_INDEX]), tol=0.0002)
        c.add("§7.5", f"{aid} post-drift mean gain", e_post,
              mean(mg[DB_DRIFT_INDEX:]), tol=0.0002)
        c.add("§7.5", f"{aid} pre-drift r_sl", e_slpre,
              mean(sl[:DB_DRIFT_INDEX]), tol=0.0002)
        c.add("§7.5", f"{aid} post-drift r_sl", e_slpost,
              mean(sl[DB_DRIFT_INDEX:]), tol=0.0002)
    for aid, e_rel in [("mubit-db-3", 31.7), ("icl-db-3", 60.5)]:
        a = g(aid)
        if not a:
            continue
        mg = a["series"]["mean_gain_by_index"]
        pre, post = mean(mg[:DB_DRIFT_INDEX]), mean(mg[DB_DRIFT_INDEX:])
        c.add("§7.5", f"{aid} relative gain increase", e_rel,
              (post - pre) / pre * 100 if pre else None, tol=0.15, unit="%")

    # ---- §5 / §11 memory + provenance claims -----------------------------
    c.add("§5", "system_memory is None in all 12", True,
          not any(a["system_memory_present"] for a in derived.values()))
    md3 = g("mubit-db-3")
    if md3:
        c.add("§5", "mubit-db-3 run0 distinct lesson IDs", 34,
              (db["mubit-db-3"]["runs"][0]["steps"]["distinct_lessons"] or [None])[-1])
    if v4:
        reg = bsm["mubit-bsm-v4-3.5flash"]["runs"][0]["registry_size"]
        c.add("§5", "BSM v4 run0 registry_size start", 2, reg[0])
        c.add("§5", "BSM v4 run0 registry_size final", 21, reg[-1])

    c.add("§1", "total stored interactions", 11835,
          sum(a["total_interactions"] for a in derived.values()))

    # ---- §11 per-run DB scores overlap -----------------------------------
    for aid, e in [("mubit-db-3", [0.2050, 0.1217, 0.2133]),
                   ("icl-db-3", [0.1133, 0.1767, 0.1450])]:
        a = g(aid)
        if a:
            c.add("§11.1", f"{aid} per-run scores", e,
                  [r["score"] for r in a["runs"]], tol=0.0002)

    # ---- §11 "Present but degraded" — the null latency index --------------
    for aid in ("mubit-poker-v5-3.5flash", "mubit-poker-full-3.5flash"):
        a = g(aid)
        if not a:
            continue
        nulls = [i for i, v in enumerate(a["series"]["mean_latency_by_index"]) if v is None]
        c.add("§11-deg", f"{aid} latency null index", 119,
              nulls[0] if nulls else None)

    # ---- baseline per-instance detail IS recoverable (not in the report) ---
    c.add("new", "BSM baseline per-scan scoring recoverable", True,
          all(len((v.get("baseline") or {}).get("scans") or []) == 90 for v in bsm.values()))
    c.add("new", "Poker baseline per-hand history recoverable", True,
          all(len((v.get("baseline") or {}).get("hands") or []) > 0 for v in poker.values()))
    c.add("new", "DB baseline per-question outcomes recoverable", True,
          all(len((v.get("baseline") or {}).get("outcomes") or []) > 0 for v in db.values()))

    # ---- and that the recovered order is REAL, not a stable-sort accident ---
    # Each sub-trace reports scan_idx=0 / hand_num=1, so instance_traces order
    # is the only ordering available. Check it elementwise against the
    # independently-aggregated baseline_reward_by_index.
    for aid, v in bsm.items():
        got = [s["score"] for s in v["baseline"]["scans"]]
        want = derived[aid]["series"]["baseline_reward_by_index"]
        c.add("new", f"{aid} baseline order matches reward series", 0,
              max((abs(a - b) for a, b in zip(got, want)), default=None), tol=1e-6)
    for aid, v in poker.items():
        got = [(h["profit"] or 0) / 10.0 for h in v["baseline"]["hands"]]
        want = derived[aid]["series"]["baseline_reward_by_index"]
        if got:
            c.add("new", f"{aid} baseline order matches reward series", 0,
                  max((abs(a - b) for a, b in zip(got, want)), default=None), tol=1e-6)
    # DB reward is NOT binary correctness — it is query-efficiency weighted.
    # Checking the recovered outcomes against the derived formula verifies the
    # ordering AND the reward definition in one pass.
    for aid, v in db.items():
        B = derived[aid]["task_params"].get("max_queries_per_question")
        outs = v["baseline"]["outcomes"]
        want = derived[aid]["series"]["baseline_reward_by_index"]
        if not (outs and B):
            continue
        got = [((B - o["num_queries"]) / B) if o["correct"] else 0.0 for o in outs]
        c.add("new", f"{aid} baseline reward == correct?(B-q)/B:0", 0,
              max((abs(a - b) for a, b in zip(got, want)), default=None), tol=1e-3)

    # ---- §11.7 cost is unusable on 3.5-flash ------------------------------
    bad = [a["id"] for a in derived.values()
           if "3.5flash" in a["id"] or a["model"] == "gemini-3.5-flash"]
    c.add("§11.7", "no 3.5-flash artifact has usable cost", True,
          all(not derived[i]["usage"]["cost_reliable"] for i in bad if i in derived))

    # ---- §7.2 is NOT verified here (out of scope by decision) ------------
    return c


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

def print_table(c: Checks):
    W = 118
    print("=" * W)
    print("VERIFICATION — DEMO_DATA_REPORT.md re-derived from results/*.json.gz")
    print("=" * W)
    cur = None
    for r in c.rows:
        if r["section"] != cur:
            cur = r["section"]
            print(f"\n{cur}")
            print(f"  {'claim':<42} {'expected':>18} {'actual':>18} {'delta':>14}  status")
            print(f"  {'-' * (W - 4)}")
        mark = {"PASS": "ok ", "MISMATCH": "XX ", "NO DATA": "-- "}[r["status"]]
        d = "" if r["delta"] is None else f"{r['delta']:+.4f}"
        print(f"  {r['claim']:<42} {fmt_val(r['expected'], r['unit']):>18} "
              f"{fmt_val(r['actual'], r['unit']):>18} {d:>14}  {mark}{r['status']}")
    n = c.counts()
    print("\n" + "=" * W)
    print(f"RESULT: {n['PASS']} PASS   {n['MISMATCH']} MISMATCH   {n['NO DATA']} NO DATA")
    print("=" * W)
    if n["MISMATCH"]:
        print("\nMISMATCHES:")
        for r in c.rows:
            if r["status"] == "MISMATCH":
                print(f"  [{r['section']}] {r['claim']}: "
                      f"report says {fmt_val(r['expected'], r['unit'])}, "
                      f"artifacts say {fmt_val(r['actual'], r['unit'])}")
    print("\nNOT VERIFIED HERE (no chart can show it; needs source + git history):")
    print("  §7.2  BSM_SYSTEM_PROMPT in systems/mubit_bsm/system.py naming "
          "ground-truth grid frequencies")


def write_js(path: Path, global_name: str, payload: dict):
    path.write_text(
        f"window.{global_name} = " + json.dumps(payload, separators=(",", ":")) + ";\n"
    )


def main():
    verify_only = "--verify" in sys.argv

    derived, bsm, db, poker = {}, {}, {}, {}
    for task, aid, path in discover():
        d = load_artifact(path)
        derived[aid] = derive(task, aid, d)
        if task == "blind_spectrum_monitoring":
            bsm[aid] = extract_bsm(d)
        elif task == "database_exploration":
            db[aid] = extract_db(d)
        elif task == "exploitable_poker":
            poker[aid] = extract_poker(d)
        del d

    checks = verify(derived, bsm, db, poker)
    print_table(checks)

    if verify_only:
        return 0 if checks.counts()["MISMATCH"] == 0 else 1

    OUT_DIR.mkdir(exist_ok=True)
    index = {
        "generated_from": "results/*.json.gz",
        "artifacts": derived,
        "verification": checks.rows,
        "verification_counts": checks.counts(),
        "r_max": R_MAX,
        "db_drift_index": DB_DRIFT_INDEX,
    }
    payloads = [
        ("index", "VIZ_INDEX", index),
        ("bsm", "VIZ_BSM", {"spectrum": bsm,
                            "artifacts": {k: v for k, v in derived.items()
                                          if v["task"] == "blind_spectrum_monitoring"}}),
        ("db", "VIZ_DB", {"detail": db,
                          "artifacts": {k: v for k, v in derived.items()
                                        if v["task"] == "database_exploration"}}),
        ("poker", "VIZ_POKER", {"detail": poker,
                                "artifacts": {k: v for k, v in derived.items()
                                              if v["task"] == "exploitable_poker"}}),
    ]
    print("\nWROTE:")
    for name, gname, payload in payloads:
        jp, sp = OUT_DIR / f"{name}.json", OUT_DIR / f"{name}.js"
        jp.write_text(json.dumps(payload, indent=1))
        write_js(sp, gname, payload)
        print(f"  viz_data/{name}.js   {sp.stat().st_size / 1024:8.1f} KB   (window.{gname})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
