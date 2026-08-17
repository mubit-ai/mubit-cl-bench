"""Re-derive the significance analysis from the paper's shipped artifacts.

Usage: python3 scripts/significance_analysis.py  (run inside a clone of
pgasawa/continual-learning-bench; reads final_results/runs/*/task_artifacts.json.gz)
A gain is flagged n.s. when |gain| < 2 x std of the 5 stateful run means.
"""
import gzip, json, statistics, glob, os

def outcomes(t):
    base = t['baseline_trace'].get('instance_outcomes') or []
    runs = []
    for r in t.get('run_traces') or []:
        o = (r.get('trace') or {}).get('instance_outcomes') or []
        if o: runs.append([x['reward'] for x in o])
    return [x['reward'] for x in base], runs

for task in ['cohort_studies', 'codebase_adaptation', 'sales_prediction']:
    print(f"\n=== {task} ===")
    for path in sorted(glob.glob('final_results/runs/*/task_artifacts.json.gz')):
        system = path.split('/')[-2]
        data = json.load(gzip.open(path))
        t = data.get(task)
        if not t: continue
        base, runs = outcomes(t)
        if not base or not runs: continue
        r_sl = statistics.mean(base)
        run_means = [statistics.mean(r) for r in runs]
        gain = statistics.mean(run_means) - r_sl
        sigma = statistics.stdev(run_means) if len(run_means) > 1 else 0.0
        sig = "SIG" if abs(gain) > 2*sigma else "n.s."
        print(f"{system:28s} gain={gain:+.3f} sigma={sigma:.3f} {sig}")
